from prometheus_client import Counter, Gauge

profiles_created_total = Counter(
    "profiles_created_total",
    "Total profiles auto-created on first /profiles/me hit",
)

creators_activated_total = Counter(
    "creators_activated_total",
    "Total users who activated creator mode",
)

tiers_created_total = Counter(
    "tiers_created_total",
    "Total tiers created by creators",
)

tiers_updated_total = Counter(
    "tiers_updated_total",
    "Total tier updates",
)

subscriptions_created_total = Counter(
    "subscriptions_created_total",
    "Total subscriptions created via internal API",
)

subscriptions_cancelled_total = Counter(
    "subscriptions_cancelled_total",
    "Total subscriptions cancelled via internal API",
)

subscriptions_expired_total = Counter(
    "subscriptions_expired_total",
    "Total subscriptions expired by the background task",
)

active_subscriptions = Gauge(
    "active_subscriptions",
    "Current number of active subscriptions (updated every expiry-task cycle)",
)

analytics_proxy_requests_total = Counter(
    "analytics_proxy_requests_total",
    "Total analytics proxy calls from this service",
    ["result"],  # "success" | "unavailable"
)
