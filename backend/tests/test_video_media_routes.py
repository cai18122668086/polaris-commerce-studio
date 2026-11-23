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


COS = "https://rh-images-1252422369.cos.ap-beijing.myqcloud.com/tts/a.mp3?sign=abc"


def test_tencent_cos_regional_goes_through_same_bucket_acceleration():
    routes = {"rh-images-1252422369.cos.ap-beijing.myqcloud.com": "rh-images-1252422369.cos.accelerate.myqcloud.com"}
    assert routed_media_url(COS, routes) == "https://rh-images-1252422369.cos.accelerate.myqcloud.com/tts/a.mp3?sign=abc"
    assert routed_media_url(COS, {"rh-images-1252422369.cos.ap-beijing.myqcloud.com": "other-1.cos.accelerate.myqcloud.com"}) == COS


def test_tts_audio_host_is_an_allowed_media_host():
    from app.video_providers import safe_media_url
    assert safe_media_url(COS) == COS
