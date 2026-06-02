from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # WebSocket URL: ws://host/ws/chat/conversations/{conversation_id}/?token=JWT_TOKEN
    re_path(r'^ws/chat/conversations/(?P<conversation_id>\d+)/$', consumers.ChatConsumer.as_asgi()),
]
