import enum


class SubscriptionStatus(enum.StrEnum):
    active = "active"
    cancelled = "cancelled"
    expired = "expired"
