from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


class ChatAnonRateThrottle(AnonRateThrottle):
    scope = 'chat_anon'


class ChatUserRateThrottle(UserRateThrottle):
    scope = 'chat_user'
