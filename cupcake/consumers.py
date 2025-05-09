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

class SummaryConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.user_id = str(self.scope["user"].id)
        print(self.user_id)
        await self.channel_layer.group_add(
            f"user_{self.user_id}_summary",
            self.channel_name
        )

        await self.accept()
        await self.send_json({"message": f"Connected to the summarization channel"})

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
        await self.channel_layer.group_add(
            f"{self.unique_id}_webrtc",
            self.channel_name
        )
        try:
            channel = await WebRTCUserChannel.objects.aget(user=self.scope["user"], channel_id=f"{self.unique_id}_webrtc")
        except WebRTCUserChannel.DoesNotExist:
            channel = await WebRTCUserChannel.objects.acreate(
                user=self.scope["user"],
                channel_id=f"{self.unique_id}_webrtc",
                channel_type="viewer"
            )
        try:
            self.session = await WebRTCSession.objects.aget(session_unique_id=self.session_id, session=session)
        except WebRTCSession.DoesNotExist:
            self.session = await WebRTCSession.objects.acreate(
                session_unique_id=self.session_id, session=session
            )


        await add_webrtc_user_channel(self.session, channel)

        await self.accept()
        await self.send_json({"message": f"Connected to the WebRTC signaling channel", "unique_id": self.unique_id})



    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            f"{self.session_id}_webrtc",
            self.channel_name
        )
        await remove_webrtc_user_channel(self.scope["user"], f"{self.unique_id}_webrtc")

    async def receive_json(self, content):
        message_type = content["type"]
        if message_type == "check":
            channels = await get_all_channels(self.session)
            for channel in channels:
                if channel.channel_id != f"{self.unique_id}_webrtc":
                    await self.channel_layer.group_send(
                        channel.channel_id,
                        {
                            "type": "check_message",
                            "from": self.unique_id,
                            "id_type": content["id_type"],
                        }
                    )
        elif message_type == "offer":
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
                offer = await WebRTCUserOffer.objects.acreate(
                user=self.scope["user"],
                sdp=content["sdp"],
                session=self.session,
                from_id=self.unique_id,
                id_type = content["id_type"],
            )

            if content["to"]:
                try:
                    channel = await WebRTCUserChannel.objects.aget(channel_id=f"{content['to']}_webrtc")
                    await self.channel_layer.group_send(
                        f"{content['to']}_webrtc",
                        {
                            "type": "offer_message",
                            "sdp": {"type": "offer", "sdp":content["sdp"]},
                            "from": self.unique_id,
                            "id_type": content["id_type"],
                        }
                    )
                except WebRTCUserChannel.DoesNotExist:
                    pass

            # channels = await get_all_channels(self.session)
            # for channel in channels:
            #     if channel.channel_id != f"{self.unique_id}_webrtc":
            #         await self.channel_layer.group_send(
            #             channel.channel_id,
            #             {
            #                 "type": "offer_message",
            #                 "sdp": {"type": "offer", "sdp":content["sdp"]},
            #                 "from": self.unique_id,
            #                 "id_type": content["id_type"],
            #             }
            #         )
            #     else:
            #         if channel.channel_type != content["id_type"]:
            #             channel.channel_type = content["id_type"]
            #             await channel.asave()
                # else:
                #     # get all offers for the session
                #     offers = await get_all_offers(self.session)
                #     for offer in offers:
                #         if content["sdp"] != offer.sdp:
                #             await self.send_json(
                #                 {
                #                     "type": "offer",
                #                     "sdp": {"type": "offer", "sdp":offer.sdp},
                #                     "id_type": offer.id_type,
                #                 }
                #             )

        elif message_type == "answer":
            if content["to"] != self.unique_id:
                await self.channel_layer.group_send(
                    f"{content['to']}_webrtc",
                    {
                        "type": "answer_message",
                        "sdp": {"type": "answer", "sdp":content["sdp"]},
                        "from": self.unique_id,
                        "id_type": content["id_type"],
                    }
                )
            #await self.send_json({"type": "answer", "sdp": content["sdp"]})
        elif message_type == "ice":
            if content["to"] != self.unique_id:
                await self.channel_layer.group_send(
                    f"{content['to']}_webrtc",
                    {
                        "type": "ice_message",
                        "candidate": content["candidate"],
                        "from": self.unique_id,
                    }
                )

            #await self.send_json({"type": "ice", "candidate": content["candidate"]})
        elif message_type == 'candidate':
            if content["to"] != self.unique_id:
                await self.channel_layer.group_send(
                    f"{content['to']}_webrtc",
                    {
                        "type": "candidate_message",
                        "candidate": content["candidate"],
                        "from": self.unique_id,
                        "id_type": content["id_type"],
                    }
                )
            #await self.send_json({"type": "candidate", "candidate": content["candidate"]})
        else:
            await self.send_json({"error": "Invalid message type"})

    async def offer_message(self, event):
        sdp = event["sdp"]
        await self.send_json({"type": "offer", "sdp": sdp, "from": event["from"], "id_type": event["id_type"]})

    async def answer_message(self, event):
        sdp = event["sdp"]
        await self.send_json({"type": "answer", "sdp": sdp, "from": event["from"], "id_type": event["id_type"]})

    async def ice_message(self, event):
        candidate = event["candidate"]
        await self.send_json({"type": "ice", "candidate": candidate, "from": event["from"]})

    async def check_message(self, event):
        await self.send_json({"type": "check", "from": event["from"]})

    async def candidate_message(self, event):
        candidate = event["candidate"]
        await self.send_json({"type": "candidate", "candidate": candidate, "from": event["from"], "id_type": event["id_type"]})

    def generate_turn_credential(self, secret, username, ttl=3600):
        timestamp = int(time.time()) + ttl
        temporary_username = str(timestamp) + ':' + username
        password = hmac.new(secret.encode(), temporary_username.encode(), hashlib.sha1)
        password = base64.b64encode(password.digest()).decode()
        return temporary_username, password


class InstrumentJobConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
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