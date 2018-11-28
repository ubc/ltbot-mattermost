import os
from mattermostdriver.exceptions import ResourceNotFound, NoAccessTokenProvided
from requests import HTTPError
from cryptography.fernet import Fernet, InvalidToken

from errbot import BotPlugin, botcmd, arg_botcmd
from mattermostsync import Sync, CourseNotFound, parse_course


class Mattermost(BotPlugin):
    """
    Syncing from ELDAP group to Mattermost team
    """
    COMMAND_PATTERN = {
        ('add ([^ ]*) to (.*)', 'add_user_to_team')
    }
    ROLES = {
        'user': 'team_user',
        'admin': 'team_user team_admin'
    }
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
            'Mattermost:mm_mapping_*': {  # only allow admins to run and can only be run in #mattermost and direct msg
                'allowrooms': ('#' + self.config['MM_CHANNEL'], ),
                'allowusers': self.config['ADMINS'] + self.bot_config.BOT_ADMINS
            },
            'Mattermost:mm_user_*': {  # only allow admins to run and can only be run in #mattermost and direct msg
                'allowrooms': ('#' + self.config['MM_CHANNEL'], ),
                'allowusers': self.config['ADMINS'] + self.bot_config.BOT_ADMINS
            },
            'Mattermost:mm_team_*': {  # only allow admins to run and can only be run in #mattermost and direct msg
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

    # def callback_mention(self, message, mentioned_people):
    #     if self.bot_identifier in mentioned_people:
    #         found = False
    #         for pattern, func_name in self.COMMAND_PATTERN:
    #             m = re.search(pattern, message.body)
    #             if m:
    #                 # acls(message, func_name)
    #                 self._bot._process_command(message, func_name, [], False)
    #                 func = getattr(self, func_name)
    #                 found = True
    #                 func(message, m)
    #
    #         if not found:
    #             self.send(message.frm, 'Sorry, I don\'t understand your command')
    #
    # def add_user_to_team(self, message, match):
    #     user = match.group(1)
    #     team = match.group(2)
    #     msg_to = None
    #     if isinstance(message.frm, RoomOccupant):
    #         msg_to = message.frm.room
    #     elif isinstance(message.frm, Person):
    #         msg_to = message.frm
    #     else:
    #         self.log.warn('Unknown message.frm field!')
    #     self.send(msg_to, 'Adding {} msg_to {}'.format(user, team))

    @botcmd
    def mm_token_set(self, message, args):
        """Set encrypted access token to be used for ad-hoc command"""
        # check if it is a valid token
        try:
            self.init_mm(args)
        except (NoAccessTokenProvided, InvalidToken):
            return 'Hmmm, it seems you have an incorrect token. Have you encrypted it?'
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

    @botcmd()
    def mm_mapping_list(self, message, args):
        """List all course mappings used for automatic syncing"""
        return str(self['course_mappings'])

    @botcmd()
    def mm_mapping_add(self, message, args):
        """Manually add a course to course mappings for automatic syncing"""
        self.course_mappings.add(args)
        self['course_mappings'] = self.course_mappings
        return 'Course {} is added to course mappings. We have {} courses in the mapping'.format(
            args, len(self['course_mappings'])
        )

    @botcmd()
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
    @arg_botcmd('--once', dest='once', action='store_true')
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

    @arg_botcmd('team_name')
    @arg_botcmd('username')
    @arg_botcmd('--role', dest='role', default='user', choices=['admin', 'user'])
    def mm_user_add(self, message, username, team_name, role):
        """Add a user to a team"""
        token = self['tokens'][message.frm.person]
        try:
            mm = self.init_mm(token)
        except Exception as e:
            yield e
            return

        try:
            team = mm.driver.teams.get_team_by_name(team_name)
        except ResourceNotFound:
            yield 'I can\'t find team under name `{}` in the system.'.format(team_name)
            return
        except Exception as e:
            yield e
            return

        try:
            user = mm.driver.users.get_user_by_username(username)
        except ResourceNotFound:
            u = mm.get_users_from_ldap(username)
            if not u:
                yield 'I can\'t find user with username `{}` in LDAP'.format(username)
                return
            created_users, failed_users = mm.create_users(u)
            if not created_users:
                yield 'I have some troubles to create user `{}`. Checkout the logs or try again later.'
                return
            user = created_users[0]

        mm.add_users_to_team([user], team['id'], self.ROLES[role])
        if role == 'admin':
            mm.driver.teams.update_team_member_roles(team['id'], user['id'], {'roles': self.ROLES[role]})

        yield 'OK, I added user `{}` to team `{}` as `{}`'.format(username, team_name, role)

    @arg_botcmd('team_name')
    @arg_botcmd('username')
    def mm_user_remove(self, message, username, team_name):
        """Remove a user from a team"""
        token = self['tokens'][message.frm.person]
        try:
            mm = self.init_mm(token)
        except Exception as e:
            yield e
            return

        try:
            team = mm.driver.teams.get_team_by_name(team_name)
        except ResourceNotFound:
            yield 'I can\'t find team under name `{}` in the system.'.format(team_name)
            return
        except Exception as e:
            yield e
            return

        try:
            user = mm.driver.users.get_user_by_username(username)
        except ResourceNotFound:
            yield 'I can\'t find user under username `{}` in the system.'.format(team_name)
            return
        except Exception as e:
            yield e
            return

        try:
            teams = mm.driver.teams.get_user_teams(user['id'])
            if team['id'] in [t['id'] for t in teams]:
                mm.driver.teams.remove_user_from_team(team['id'], user['id'])
            else:
                yield 'Hmmm, it looks like user `{}` is not in team `{}`'.format(username, team_name)
                return
        except Exception as e:
            yield e
            return

        yield 'OK, I removed user `{}` from team `{}`'.format(username, team_name)

    @arg_botcmd('team_name')
    @arg_botcmd('--display-name', dest='display_name')
    @arg_botcmd('--type', dest='team_type', default='I', choices=['O', 'I'])
    def mm_team_add(self, message, team_name, display_name, team_type):
        token = self['tokens'][message.frm.person]
        try:
            mm = self.init_mm(token)
        except Exception as e:
            return e

        if not display_name:
            display_name = team_name

        try:
            team = mm.get_team_by_name(team_name)
            if team:
                return 'Team {} already exists.'.format(team_name)
            else:
                mm.create_team(team_name, display_name, team_type)
                return 'Team {} is created.'.format(team_name)
        except HTTPError as e:
            self.log.error('Failed to create team {}: {}'.format(team_name, e.args))
            return 'Failed to create team {}: {}'.format(team_name, e.args)

    @botcmd()
    def mm_team_list(self, message, args):
        """List all teams in in Mattermost"""
        token = self['tokens'][message.frm.person]
        try:
            mm = self.init_mm(token)
        except Exception as e:
            return e

        teams = []
        for i in range(1000):
            t = mm.driver.teams.get_teams({'page': i, 'per_page': 60})
            teams.extend(t)
            if len(t) < 60:
                break

        return 'OK, here is a list of teams:\nName - Display Name\n' + '\n'.join(
            ['{} - {}'.format(t['name'], t['display_name']) for t in teams]
        ) if teams else 'I don\'t see any team.'

    def init_mm(self, token):
        mm = Sync({
            'url': self.config['MM_URL'],
            'token': self.fernet.decrypt(token.encode('utf-8')).decode('utf-8'),
            'port': self.config['MM_PORT'],
            'scheme': self.config['MM_SCHEME'],
            'debug': self.config['MM_DEBUG'],
            'ldap_uri': self.config['LDAP_URI'],
            'bind_user': self.config['LDAP_BIND_USER'],
            'bind_password': self.fernet.decrypt(
                self.config['LDAP_BIND_ENCRYPTED_PASSWORD'].encode('utf-8')).decode('utf-8')
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

        # self.send(self.build_identifier('#pan-test'), 'Sync completed!')
