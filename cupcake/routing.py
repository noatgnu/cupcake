from cupcake.consumers import TimerConsumer, AnnotationConsumer, UserConsumer, SummaryConsumer, WebRTCSignalConsumer

from django.urls import re_path

websocket_urlpatterns = [
    re_path(r'ws/timer/(?P<session_id>[\w\-]+)/$', TimerConsumer.as_asgi()),
    re_path(r'ws/annotation/(?P<session_id>[\w\-]+)/$', AnnotationConsumer.as_asgi()),
    re_path(r'ws/user/$', UserConsumer.as_asgi()),
    re_path(r'ws/summary/$', SummaryConsumer.as_asgi()),
    re_path(r'ws/webrtc_signal/(?P<session_id>[\w\-]+)/$', WebRTCSignalConsumer.as_asgi()),
]