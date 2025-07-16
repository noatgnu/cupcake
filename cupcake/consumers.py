import base64
import hashlib
import hmac
import time
import uuid

from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from cc.models import Session, WebRTCUserChannel, WebRTCSession, WebRTCUserOffer


@sync_to_async
def check_session(session_id, user):
    try:
        session = Session.objects.get(unique_id=session_id)
    except Session.DoesNotExist:
        return False
    if session.user == user:
        return True
    if session.enabled:
        return True
    if session.editors.filter(id=user.id).exists() or session.viewers.filter(id=user.id).exists():
        return True
    return False

@sync_to_async
def remove_webrtc_user_channel(user, unique_id):
    WebRTCUserChannel.objects.filter(user=user, channel_id=unique_id).delete()

@sync_to_async
def get_all_offers(session):
    return list(WebRTCUserOffer.objects.filter(session=session).all())

@sync_to_async
def add_webrtc_user_channel(webrtc_session, webrtc_channel):
    if webrtc_session.user_channels.filter(channel_id=webrtc_channel.channel_id).exists():
        return
    webrtc_session.user_channels.add(webrtc_channel)
    webrtc_session.save()

@sync_to_async
def get_all_channels(webrtc_session):
    return list(webrtc_session.user_channels.all())


class TimerConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.session_id = self.scope["url_route"]["kwargs"]["session_id"]
        # check if user owns the session or session is public
        if not await check_session(self.session_id, self.scope["user"]):
            await self.close()
            return

        await self.channel_layer.group_add(
            "timer_"+self.session_id,
            self.channel_name
        )

        await self.accept()
        await self.send_json({"message": f"Connected to the {self.session_id} timer channel"})

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.session_id,
            self.channel_name
        )

    async def receive_json(self, content):
        await self.channel_layer.group_send(
            self.session_id,
            {
                "type": "timer_message",
                "message": content,
            }
        )

    async def timer_message(self, event):
        content = event["message"]
        await self.send_json(content)


class AnnotationConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.session_id = self.scope["url_route"]["kwargs"]["session_id"]
        # check if user owns the session or session is public
        if not await check_session(self.session_id, self.scope["user"]):
            await self.close()
            return

        await self.channel_layer.group_add(
            "transcription_"+self.session_id,
            self.channel_name
        )

        await self.accept()
        await self.send_json({"message": f"Connected to the {self.session_id} annotation channel"})

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.session_id,
            self.channel_name
        )

    async def receive_json(self, content):
        await self.channel_layer.group_send(
            self.session_id,
            {
                "type": "annotation_message",
                "message": content,
            }
        )

    async def transcription_message(self, event):
        content = event["message"]
        await self.send_json(content)


class UserConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        # Check if user is authenticated
        if self.scope["user"].is_anonymous:
            await self.close()
            return

        self.user_id = str(self.scope["user"].id)
        print(self.user_id)
        await self.channel_layer.group_add(
            "user_"+self.user_id,
            self.channel_name
        )

        await self.accept()
        await self.send_json({"message": f"Connected to the {self.user_id} user channel"})

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            "user_"+self.user_id,
            self.channel_name
        )

    async def receive_json(self, content):
        await self.channel_layer.group_send(
            "user_"+self.user_id,
            {
                "type": "user_message",
                "message": content,
            }
        )

    async def user_message(self, event):
        content = event["message"]
        await self.send_json(content)

    async def download_message(self, event):
        content = event["message"]
        await self.send_json(content)

    async def import_message(self, event):
        content = event["message"]
        await self.send_json(content)

    async def maintenance_message(self, event):
        content = event["message"]
        await self.send_json(content)

    async def export_progress(self, event):
        content = event["message"]
        await self.send_json(content)

    async def import_progress(self, event):
        content = event["message"]
        await self.send_json(content)

class SummaryConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        print("SummaryConsumer: Starting connect method")

        # Check if channel layer exists
        if not hasattr(self, 'channel_layer') or self.channel_layer is None:
            print("SummaryConsumer: ERROR - No channel layer available!")
            await self.close()
            return
        print("SummaryConsumer: Channel layer is available")

        # Test Redis connection before proceeding
        try:
            print("SummaryConsumer: Testing Redis connection...")
            # Simple ping test to Redis
            await self.channel_layer.send("test-channel", {"type": "test.message"})
            print("SummaryConsumer: Redis connection test passed")
        except Exception as e:
            print(f"SummaryConsumer: Redis connection test FAILED: {e}")
            await self.close()
            return

        # Check if user is authenticated
        if self.scope["user"].is_anonymous:
            print("SummaryConsumer: User is anonymous, closing connection")
            await self.close()
            return

        print(f"SummaryConsumer: User authenticated: {self.scope['user']}")
        self.user_id = str(self.scope["user"].id)
        print(f"SummaryConsumer: User ID: {self.user_id}")

        # Try to accept connection BEFORE adding to group to isolate the issue
        print("SummaryConsumer: Accepting connection BEFORE group operations")
        try:
            await self.accept()
            print("SummaryConsumer: Connection accepted successfully")
        except Exception as e:
            print(f"SummaryConsumer: ERROR accepting connection: {e}")
            return

        # Now try group operations after accepting
        print("SummaryConsumer: Adding to channel layer group")
        try:
            await self.channel_layer.group_add(
                f"user_{self.user_id}_summary",
                self.channel_name
            )
            print("SummaryConsumer: Added to group successfully")
        except Exception as e:
            print(f"SummaryConsumer: ERROR adding to group: {e}")
            # Don't close here since connection is already accepted
            await self.send_json({"error": f"Failed to join group: {e}"})
            return

        try:
            await self.send_json({"message": f"Connected to the summarization channel"})
            print("SummaryConsumer: Welcome message sent")
        except Exception as e:
            print(f"SummaryConsumer: ERROR sending welcome message: {e}")

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            f"user_{self.user_id}_summary",
            self.channel_name
        )

    async def receive_json(self, content):
        await self.channel_layer.group_send(
            f"user_{self.user_id}_summary",
            {
                "type": "summary_message",
                "message": content,
            }
        )

    async def summary_message(self, event):
        content = event["message"]
        await self.send_json(content)


class WebRTCSignalConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.session_id = self.scope["url_route"]["kwargs"]["session_id"]
        # check if user owns the session or session is public
        if not await check_session(self.session_id, self.scope["user"]):
            await self.close()
            return

        session = await Session.objects.aget(unique_id=self.session_id)
        self.user_id = str(self.scope["user"].id)
        self.unique_id = str(uuid.uuid4())

        # Channel name used consistently
        self.channel_group_name = f"{self.unique_id}_webrtc"

        await self.channel_layer.group_add(
            self.channel_group_name,
            self.channel_name
        )

        try:
            channel = await WebRTCUserChannel.objects.aget(
                user=self.scope["user"],
                channel_id=self.channel_group_name
            )
        except WebRTCUserChannel.DoesNotExist:
            channel = await WebRTCUserChannel.objects.acreate(
                user=self.scope["user"],
                channel_id=self.channel_group_name,
                channel_type="viewer"
            )

        try:
            self.session = await WebRTCSession.objects.aget(
                session_unique_id=self.session_id,
                session=session
            )
        except WebRTCSession.DoesNotExist:
            self.session = await WebRTCSession.objects.acreate(
                session_unique_id=self.session_id,
                session=session
            )

        await add_webrtc_user_channel(self.session, channel)
        await self.accept()
        await self.send_json({
            "message": "Connected to the WebRTC signaling channel",
            "unique_id": self.unique_id
        })

    async def disconnect(self, close_code):
        # Use consistent channel name
        await self.channel_layer.group_discard(
            self.channel_group_name,
            self.channel_name
        )
        await remove_webrtc_user_channel(self.scope["user"], self.channel_group_name)

    async def receive_json(self, content):
        try:
            message_type = content.get("type")
            if not message_type:
                await self.send_json({"error": "Missing message type"})
                return

            handler_map = {
                "check": self._handle_check,
                "offer": self._handle_offer,
                "answer": self._handle_answer,
                "ice": self._handle_ice,
                "candidate": self._handle_candidate
            }

            handler = handler_map.get(message_type)
            if handler:
                await handler(content)
            else:
                await self.send_json({"error": "Invalid message type"})
        except Exception as e:
            await self.send_json({"error": f"Error processing message: {str(e)}"})

    async def _handle_check(self, content):
        channels = await get_all_channels(self.session)
        for channel in channels:
            if channel.channel_id != self.channel_group_name:
                await self.channel_layer.group_send(
                    channel.channel_id,
                    {
                        "type": "check_message",
                        "from": self.unique_id,
                        "id_type": content.get("id_type", ""),
                    }
                )

    async def _handle_offer(self, content):
        # Validate required fields
        if "sdp" not in content or "id_type" not in content:
            await self.send_json({"error": "Missing required fields for offer"})
            return

        try:
            offer = await WebRTCUserOffer.objects.aget(
                user=self.scope["user"],
                session=self.session,
                from_id=self.unique_id,
            )
            offer.sdp = content["sdp"]
            offer.id_type = content["id_type"]
            await offer.asave()
        except WebRTCUserOffer.DoesNotExist:
            await WebRTCUserOffer.objects.acreate(
                user=self.scope["user"],
                sdp=content["sdp"],
                session=self.session,
                from_id=self.unique_id,
                id_type=content["id_type"],
            )

        if content.get("to"):
            try:
                channel_id = f"{content['to']}_webrtc"
                await WebRTCUserChannel.objects.aget(channel_id=channel_id)
                await self.channel_layer.group_send(
                    channel_id,
                    {
                        "type": "offer_message",
                        "sdp": {"type": "offer", "sdp": content["sdp"]},
                        "from": self.unique_id,
                        "id_type": content["id_type"],
                    }
                )
            except WebRTCUserChannel.DoesNotExist:
                await self.send_json({"error": f"Target channel not found: {content['to']}"})

    async def _handle_answer(self, content):
        if "to" not in content or content["to"] == self.unique_id:
            return

        await self.channel_layer.group_send(
            f"{content['to']}_webrtc",
            {
                "type": "answer_message",
                "sdp": {"type": "answer", "sdp": content["sdp"]},
                "from": self.unique_id,
                "id_type": content.get("id_type", ""),
            }
        )

    async def _handle_ice(self, content):
        if "to" not in content or content["to"] == self.unique_id:
            return

        await self.channel_layer.group_send(
            f"{content['to']}_webrtc",
            {
                "type": "ice_message",
                "candidate": content["candidate"],
                "from": self.unique_id,
            }
        )

    async def _handle_candidate(self, content):
        if "to" not in content or content["to"] == self.unique_id:
            return

        await self.channel_layer.group_send(
            f"{content['to']}_webrtc",
            {
                "type": "candidate_message",
                "candidate": content["candidate"],
                "from": self.unique_id,
                "id_type": content.get("id_type", ""),
            }
        )

    # Message handlers - no changes
    async def offer_message(self, event):
        await self.send_json({
            "type": "offer",
            "sdp": event["sdp"],
            "from": event["from"],
            "id_type": event["id_type"]
        })

    async def answer_message(self, event):
        await self.send_json({
            "type": "answer",
            "sdp": event["sdp"],
            "from": event["from"],
            "id_type": event["id_type"]
        })

    async def ice_message(self, event):
        await self.send_json({
            "type": "ice",
            "candidate": event["candidate"],
            "from": event["from"]
        })

    async def check_message(self, event):
        await self.send_json({
            "type": "check",
            "from": event["from"]
        })

    async def candidate_message(self, event):
        await self.send_json({
            "type": "candidate",
            "candidate": event["candidate"],
            "from": event["from"],
            "id_type": event["id_type"]
        })

    def generate_turn_credential(self, secret, username, ttl=3600):
        timestamp = int(time.time()) + ttl
        temporary_username = f"{timestamp}:{username}"
        password = hmac.new(secret.encode(), temporary_username.encode(), hashlib.sha1)
        password = base64.b64encode(password.digest()).decode()
        return temporary_username, password

class InstrumentJobConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        # Check if user is authenticated
        if self.scope["user"].is_anonymous:
            await self.close()
            return

        self.user_id = str(self.scope["user"].id)
        await self.channel_layer.group_add(
            f"user_{self.user_id}_instrument_job",
            self.channel_name
        )

        await self.accept()
        await self.send_json({"message": f"Connected to the instrument job channel"})

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            f"user_{self.user_id}_instrument_job",
            self.channel_name
        )

    async def receive_json(self, content):
        await self.channel_layer.group_send(
            f"user_{self.user_id}_instrument_job",
            {
                "type": "instrument_job_message",
                "message": content,
            }
        )

    async def instrument_job_message(self, event):
        content = event["message"]
        await self.send_json(content)

    async def download_message(self, event):
        content = event["message"]
        await self.send_json(content)


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        # Check if user is authenticated
        if self.scope["user"].is_anonymous:
            await self.close()
            return

        self.user_id = str(self.scope["user"].id)

        await self.channel_layer.group_add(
            f"user_{self.user_id}_notifications",
            self.channel_name
        )

        await self.accept()
        await self.send_json({"message": "Connected to notification channel"})

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            f"user_{self.user_id}_notifications",
            self.channel_name
        )

    async def receive_json(self, content):
        await self.channel_layer.group_send(
            f"user_{self.user_id}_notifications",
            {
                "type": "notification_message",
                "message": content,
            }
        )

    # Handler for general notifications
    async def notification_message(self, event):
        content = event["message"]
        await self.send_json(content)

    # Handlers for specific notification types
    async def alert_message(self, event):
        content = event["message"]
        await self.send_json({
            "type": "alert",
            "data": content
        })

    async def info_message(self, event):
        content = event["message"]
        await self.send_json({
            "type": "info",
            "data": content
        })

    async def error_message(self, event):
        content = event["message"]
        await self.send_json({
            "type": "error",
            "data": content
        })


class MCPAnalysisConsumer(AsyncJsonWebsocketConsumer):
    """WebSocket consumer for MCP analysis task progress updates."""
    
    async def connect(self):
        # Check if user is authenticated
        if self.scope["user"].is_anonymous:
            await self.close()
            return
        
        self.user_id = str(self.scope["user"].id)
        
        # Add to group for this user's MCP analysis updates
        await self.channel_layer.group_add(
            f"user_{self.user_id}_mcp_analysis",
            self.channel_name
        )
        
        await self.accept()
        await self.send_json({"message": "Connected to MCP analysis channel"})
    
    async def disconnect(self, close_code):
        # Remove from group
        await self.channel_layer.group_discard(
            f"user_{self.user_id}_mcp_analysis",
            self.channel_name
        )

    async def receive_json(self, content):
        # Echo back any received content (for debugging)
        await self.send_json({"echo": content})
    
    async def mcp_analysis_update(self, event):
        """Handle MCP analysis progress updates."""
        content = event["message"]
        await self.send_json({
            "type": "analysis_update",
            "data": content
        })


