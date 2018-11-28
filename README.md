# Mattermost Plugin

This plugins syncs LDAP groups to Mattermost teams

## Configuration

```
!plugin config Mattermost {'ADMINS': ('@mmadmin',),
'LDAP_BIND_ENCRYPTED_PASSWORD': 'ENCRYPTED_PASSWORD',
'LDAP_BIND_USER': 'cn=username,ou=org,dc=example,dc=com',
'LDAP_SEARCH_BASE': 'ou=BASE,dc=example,dc=com',
'LDAP_URI': 'ldaps://localhost:636',
'MM_CHANNEL': '#mattermost',
'MM_DEBUG': False,
'MM_ENCRYPTED_ACCESS_TOKEN': None,
'MM_PORT': 443,
'MM_SCHEME': 'https',
'MM_URL': 'https://mattermost.example.com',
'SYNC_FREQUENCY': 600}
```

## Course Name Spec

Please see [here](https://github.com/ubc/mattermost-sync#course-name-spec) for details.

## Bot Commands

* *!mm mapping add* - Manually add a course to course mappings for automatic syncing
    * !mm mapping add [COURSE_NAME_SPEC](https://github.com/ubc/mattermost-sync#course-name-spec)
* *!mm mapping list* - List all course mappings used for automatic syncing
* *!mm mapping remove* - Remove a course to course mappings for automatic syncing
    * !mm mapping remove [COURSE_NAME_SPEC](https://github.com/ubc/mattermost-sync#course-name-spec)
* *!mm scheduler start* - Start scheduler for automatic syncing
* *!mm scheduler stop* - Stop scheduler for automatic syncing
* *!mm sync* - usage: mm_sync [-h] [--once] course_spec
    * When a course is synced with this command, it is added to course mapping by default unless 
    `--once` option is specified. The scheduler will use the mapping to do automatic syncing.
    * !mm sync [COURSE_NAME_SPEC](https://github.com/ubc/mattermost-sync#course-name-spec)
    * !mm sync CPSC_101_101_2018W
    * !mm sync CPSC_101_101_2018W=CUSTOM-TEAM-NAME
    * !mm sync CPSC_101_101_2018W+CPSC_101_201_2018W=CUSTOM-TEAM-NAME
* *!mm team add* - Add a team, usage: mm_team_add [-h] [--type {O,I}] [--display-name DISPLAY_NAME] team_name
    * Display name is optional. Default is the value of `team_name`
    * Type: can be `Open` or `Invite`, default: `Invite`
* *!mm team list* - List all teams in in Mattermost
* *!mm token list* - List all encrypted access token stored
* *!mm token set* - Set encrypted access token to be used for ad-hoc command
    * !mm token set ENCRYPTED_ACCESS_TOKEN
* *!mm token show* - Show encrypted access token to be used for ad-hoc command
* *!mm user add* - usage: mm_user_add [-h] [--role {admin,user}] username team_name
    * Add a user to a team
    * By default, adding as user/member role
* *!mm user remove* - usage: mm_user_remove [-h] username team_name
    * Remove a user from a team