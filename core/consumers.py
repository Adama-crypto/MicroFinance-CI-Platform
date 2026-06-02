import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from .models import ChatConversation, ChatMessage

User = get_user_model()


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.conversation_id = self.scope['url_route']['kwargs']['conversation_id']
        self.room_group_name = f'chat_{self.conversation_id}'
        self.user = self.scope.get('user')

        # Check if user is authenticated
        if not self.user or self.user.is_anonymous:
            await self.close(code=4003)  # Policy violation (anonymous access forbidden)
            return

        # Check if the user has permission to join this conversation
        is_member = await self.check_conversation_membership()
        if not is_member:
            await self.close(code=4003)
            return

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()
        
        # Broadcast presence (user is online)
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'user_presence',
                'username': self.user.username,
                'role': self.user.role,
                'status': 'online'
            }
        )

    async def disconnect(self, close_code):
        # Leave room group
        if hasattr(self, 'room_group_name'):
            # Broadcast offline presence
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'user_presence',
                    'username': self.user.username,
                    'role': self.user.role,
                    'status': 'offline'
                }
            )
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )

    # Receive message from WebSocket client
    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        event_type = data.get('type')
        
        if event_type == 'chat_message':
            message_content = data.get('message', '').strip()
            if message_content:
                # Save message to database
                msg = await self.save_message(message_content)
                
                # Broadcast message to the group
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'chat_message_broadcast',
                        'id': msg.id,
                        'sender_username': self.user.username,
                        'sender_role': self.user.role,
                        'message': message_content,
                        'timestamp': msg.timestamp.isoformat()
                    }
                )
        elif event_type == 'typing':
            is_typing = data.get('typing', False)
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'chat_typing_broadcast',
                    'username': self.user.username,
                    'typing': is_typing
                }
            )

    # Handlers for events sent to the group

    async def chat_message_broadcast(self, event):
        # Send message back to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'chat_message',
            'id': event['id'],
            'sender_username': event['sender_username'],
            'sender_role': event['sender_role'],
            'message': event['message'],
            'timestamp': event['timestamp']
        }))

    async def chat_typing_broadcast(self, event):
        # Send typing indicator to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'typing',
            'username': event['username'],
            'typing': event['typing']
        }))

    async def user_presence(self, event):
        # Send presence status to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'presence',
            'username': event['username'],
            'role': event['role'],
            'status': event['status']
        }))

    @database_sync_to_async
    def check_conversation_membership(self):
        try:
            conv = ChatConversation.objects.get(id=self.conversation_id)
            # Staff can join any conversation. Clients only their own.
            if self.user.role in ['AGENT', 'ADMIN']:
                return True
            return conv.client == self.user
        except ChatConversation.DoesNotExist:
            return False

    @database_sync_to_async
    def save_message(self, message):
        conv = ChatConversation.objects.get(id=self.conversation_id)
        return ChatMessage.objects.create(
            conversation=conv,
            sender=self.user,
            message=message
        )
