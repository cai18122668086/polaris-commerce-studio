from app.video_providers import routed_media_url

ROUTES = {"sowa.oss-cn-beijing.aliyuncs.com": "sowa.oss-accelerate.aliyuncs.com"}
URL = "https://sowa.oss-cn-beijing.aliyuncs.com/a/b.mp4?Expires=1&Signature=x%2By"


def test_regional_oss_goes_through_same_bucket_acceleration_keeping_signature():
    assert routed_media_url(URL, ROUTES) == (
        "https://sowa.oss-accelerate.aliyuncs.com/a/b.mp4?Expires=1&Signature=x%2By"
    )


def test_no_route_configured_leaves_url_untouched():
    assert routed_media_url(URL, {}) == URL


def test_routes_to_other_hosts_or_buckets_are_ignored():
    assert routed_media_url(URL, {"sowa.oss-cn-beijing.aliyuncs.com": "evil.example.com"}) == URL
    assert routed_media_url(URL, {"sowa.oss-cn-beijing.aliyuncs.com": "other.oss-accelerate.aliyuncs.com"}) == URL
    other = "https://quanyu.sowa.chat/x.mp4"
    assert routed_media_url(other, {"quanyu.sowa.chat": "sowa.oss-accelerate.aliyuncs.com"}) == other
