import os
from requests import HTTPError
from cryptography.fernet import Fernet

from errbot import BotPlugin, botcmd, arg_botcmd
from mattermostsync import Sync, CourseNotFound, parse_course


class Mattermost(BotPlugin):
    """
    Syncing from ELDAP group to Mattermost team
    """
    tokens = {}
    course_mappings = set()
    fernet = None

    def activate(self):
        """
        Triggers on plugin activation

        You should delete it if you're not using it to override any default behaviour
        """
        if not self.config:
            self.log.info('Mattermost is not configured. Forbid activation')
            return

        key = os.environ.get('ENCRYPTION_KEY')
        if not key:
            raise ValueError('Missing encryption key. Please set ENCRYPTION_KEY environment variable.')

        # init Fernet with decrypt token
        self.fernet = Fernet(key.encode('utf-8'))

        # need to activate plugin before accessing storage
        super(Mattermost, self).activate()

        if 'tokens' not in self:
            self['tokens'] = {}
        self.tokens = self['tokens']

        if 'course_mappings' not in self:
            self['course_mappings'] = set()
        self.course_mappings = self['course_mappings']

        # add additional acls
        self.bot_config.ACCESS_CONTROLS.update({
            'Mattermost:mm_sync': {  # only allow admins to run and can only be run in #mattermost and direct msg
                'allowrooms': ('#' + self.config['MM_CHANNEL'], ),
                'allowusers': self.config['ADMINS'] + self.bot_config.BOT_ADMINS
            },
            'Mattermost:mm_token_*': {'allowmuc': False},  # only allow direct msg
            'Mattermost:mm_scheduler_*': {  # only allow admins to run and can only be run in #mattermost and direct msg
                'allowrooms': ('#' + self.config['MM_CHANNEL'], ),
                'allowusers': self.config['ADMINS'] + self.bot_config.BOT_ADMINS
            },
        })

        # start scheduler
        if self.config['MM_ENCRYPTED_ACCESS_TOKEN']:
            self.start_poller(self.config['SYNC_FREQUENCY'], self.refresh)
            self.log.info('Mattermost auto sync scheduler started')

    def deactivate(self):
        """
        Triggers on plugin deactivation

        You should delete it if you're not using it to override any default behaviour
        """
        super(Mattermost, self).deactivate()

    def get_configuration_template(self):
        """
        Defines the configuration structure this plugin supports
        """
        return {
            'MM_URL': 'https://mattermost.example.com',
            'MM_PORT': 443,
            'MM_SCHEME': 'https',
            'MM_CHANNEL': '#mattermost',
            'MM_DEBUG': False,
            'MM_ENCRYPTED_ACCESS_TOKEN': None,
            'LDAP_URI': 'ldaps://localhost:636',
            'LDAP_BIND_USER': 'cn=username,ou=org,dc=example,dc=com',
            'LDAP_BIND_ENCRYPTED_PASSWORD': 'ENCRYPTED_PASSWORD',
            'LDAP_SEARCH_BASE': 'ou=BASE,dc=example,dc=com',
            'ADMINS': ('@mmadmin',),
            'SYNC_FREQUENCY': 600
        }

    def check_configuration(self, configuration):
        """
        Triggers when the configuration is checked, shortly before activation

        Raise a errbot.utils.ValidationException in case of an error

        You should delete it if you're not using it to override any default behaviour
        """
        super(Mattermost, self).check_configuration(configuration)

    def callback_connect(self):
        """
        Triggers when bot is connected

        You should delete it if you're not using it to override any default behaviour
        """
        pass

    def callback_message(self, message):
        """
        Triggered for every received message that isn't coming from the bot itself

        You should delete it if you're not using it to override any default behaviour
        """
        pass

    def callback_botmessage(self, message):
        """
        Triggered for every message that comes from the bot itself

        You should delete it if you're not using it to override any default behaviour
        """
        pass

    @botcmd
    def mm_token_set(self, message, args):
        """Set encrypted access token to be used for ad-hoc command"""
        self.tokens[message.frm.person] = args
        self['tokens'] = self.tokens
        return "Mattermost access token is set"

    @botcmd
    def mm_token_show(self, message, args):
        """Show encrypted access token to be used for ad-hoc command"""
        if 'tokens' not in self or message.frm.person not in self['tokens']:
            return 'No token'
        else:
            return str(self['tokens'][message.frm.person])

    @botcmd(admin_only=True)
    def mm_token_list(self, message, args):
        """List all encrypted access token stored"""
        if 'tokens' in self:
            return str(self['tokens'])
        else:
            return '{}'

    @botcmd(admin_only=True)
    def mm_mapping_list(self, message, args):
        """List all course mappings used for automatic syncing"""
        return str(self['course_mappings'])

    @botcmd(admin_only=True)
    def mm_mapping_add(self, message, args):
        """Manually add a course to course mappings for automatic syncing"""
        self.course_mappings.add(args)
        self['course_mappings'] = self.course_mappings
        return 'Course {} is added to course mappings. We have {} courses in the mapping'.format(
            args, len(self['course_mappings'])
        )

    @botcmd(admin_only=True)
    def mm_mapping_remove(self, message, args):
        """Remove a course to course mappings for automatic syncing"""
        self.course_mappings.remove(args)
        self['course_mappings'] = self.course_mappings
        return 'Course {} is removed from course mappings. We have {} courses in the mapping'.format(
            args, len(self['course_mappings'])
        )

    @botcmd(admin_only=True)
    def mm_scheduler_start(self, message, args):
        """Start scheduler for automatic syncing"""
        if not self.config['MM_ENCRYPTED_ACCESS_TOKEN']:
            yield 'I need MM_ENCRYPTED_ACCESS_TOKEN in the configuration to be set in order to use scheduled sync.'
            return
        self.start_poller(self.config['SYNC_FREQUENCY'], self.refresh)
        yield 'OK, automatic sync started.'

    @botcmd(admin_only=True)
    def mm_scheduler_stop(self, message, args):
        """Stop scheduler for automatic syncing"""
        self.stop_poller(self.refresh)
        yield 'OK, automatic sync stopped.'

    @arg_botcmd('course_spec')
    @arg_botcmd('--once', dest='once', action='store_false')
    def mm_sync(self, message, course_spec, once):
        """Ad-hoc sync LDAP to MM team"""
        if course_spec.lower() == 'all':
            courses = self['course_mappings']
        else:
            courses = (course_spec,)

        # check if personal token is set
        if 'tokens' not in self or message.frm.person not in self['tokens']:
            yield 'Please use `!mm token set ENCRYPTED_ACCESS_TOKEN` to set up Mattermost access token.'

        token = self['tokens'][message.frm.person]

        try:
            mm = self.init_mm(token)
        except Exception as e:
            yield e
            return

        for msg in self.sync(courses, mm):
            yield msg

        # store the mapping
        if course_spec.lower() != 'all' and not once:
            self.course_mappings.add(course_spec)
            self['course_mappings'] = self.course_mappings

        return

    def init_mm(self, token):
        mm = Sync({
            'url': self.config['MM_URL'],
            'token': self.fernet.decrypt(token.encode('utf-8')).decode('utf-8'),
            'port': self.config['MM_PORT'],
            'scheme': self.config['MM_SCHEME'],
            'debug': self.config['MM_DEBUG']
        })
        mm.driver.login()

        return mm

    def sync(self, courses, mm):
        """Actual sync function, also a generator"""
        for course in courses:

            source_courses, team_name = parse_course(course)
            yield 'OK, syncing course(s) {} to team {}.'.format(source_courses, team_name)

            try:
                course_members = []
                for c in source_courses:
                    course_members.extend(mm.get_member_from_ldap(
                        self.config['LDAP_URI'], self.config['LDAP_BIND_USER'],
                        self.fernet.decrypt(
                            self.config['LDAP_BIND_ENCRYPTED_PASSWORD'].encode('utf-8')).decode('utf-8'),
                        self.config['LDAP_SEARCH_BASE'],
                        *c))
            except CourseNotFound as e:
                yield e
                continue

            try:
                team = mm.get_team_by_name(team_name)
                if team:
                    yield 'Team {} already exists.'.format(team_name)
                else:
                    team = mm.create_team(team_name)
                    yield 'Team {} is created.'.format(team_name)
                yield 'Now adding students to the team...'
                existing_users, failed_users = mm.create_users(course_members)
                if failed_users:
                    yield 'Warning: failed to add {} students to Mattermost. Please check the logs for details.'.format(
                        len(failed_users)
                    )

                # check if the users are already in the team
                members = []
                for i in range(1000):
                    m = mm.get_team_members(team['id'], {'page': i, 'per_page': 60})
                    if m:
                        members.extend(m)
                        continue

                    if len(m) < 60:
                        break
                member_ids = [m['user_id'] for m in members]
                users_to_add = []
                for u in existing_users:
                    if u['id'] not in member_ids:
                        users_to_add.append(u)

                # add the missing ones
                if users_to_add:
                    mm.add_users_to_team(users_to_add, team['id'])
                    yield 'Added {} students to the team {}.'.format(len(users_to_add), team_name)
                else:
                    yield 'No new student to add. Roster is up-to-date.'
            except HTTPError as e:
                self.log.error('Failed to sync team {}: {}'.format(team_name, e.args))
                yield 'Failed to sync team {}: {}'.format(team_name, e.args)
                return
            yield 'Finished to sync course {}.'.format(course)

    def refresh(self):
        """Refresh the team members"""
        courses = self['course_mappings']

        mm = self.init_mm(self.config['MM_ENCRYPTED_ACCESS_TOKEN'])

        for msg in self.sync(courses, mm):
            self.log.info(msg)

        self.send(self.build_identifier('#pan-test'), 'Sync completed!')
