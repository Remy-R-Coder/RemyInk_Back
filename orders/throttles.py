from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


class OrdersAnonRateThrottle(AnonRateThrottle):
    scope = 'orders_anon'


class OrdersUserRateThrottle(UserRateThrottle):
    scope = 'orders_user'
