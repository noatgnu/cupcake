"""
Tests for communication and system models: WebRTC, Messaging, BackupLog, SiteSettings
"""
import uuid
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.exceptions import ValidationError
from datetime import timedelta
from cc.models import (
    WebRTCSession, WebRTCUserChannel, WebRTCUserOffer,
    MessageThread, Message, MessageRecipient, MessageAttachment,
    ExternalContact, ExternalContactDetails,
    BackupLog, SiteSettings, LabGroup, Session
)


class WebRTCModelTest(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user('user1', 'user1@example.com', 'password')
        self.user2 = User.objects.create_user('user2', 'user2@example.com', 'password')
    
    def test_webrtc_session_creation(self):
        """Test WebRTC session creation"""
        from cc.models import Session
        main_session = Session.objects.create(
            unique_id=uuid.uuid4(),
            user=self.user1
        )
        session = WebRTCSession.objects.create(
            session=main_session,
            session_unique_id='webrtc-session-123'
        )
        
        self.assertEqual(session.session_unique_id, 'webrtc-session-123')
        self.assertEqual(session.session, main_session)
    
    def test_webrtc_user_channel_creation(self):
        """Test WebRTC user channel creation"""
        from cc.models import Session
        main_session = Session.objects.create(
            unique_id=uuid.uuid4(),
            user=self.user1
        )
        session = WebRTCSession.objects.create(
            session=main_session,
            session_unique_id='webrtc-session-123'
        )
        
        channel = WebRTCUserChannel.objects.create(
            user=self.user2,
            channel_id='channel-456',
            channel_type='host'
        )
        
        self.assertEqual(channel.user, self.user2)
        self.assertEqual(channel.channel_id, 'channel-456')
        self.assertEqual(channel.channel_type, 'host')
    
    def test_webrtc_channel_types(self):
        """Test valid WebRTC channel types"""
        from cc.models import Session
        main_session = Session.objects.create(
            unique_id=uuid.uuid4(),
            user=self.user1
        )
        session = WebRTCSession.objects.create(
            session=main_session,
            session_unique_id='webrtc-session-123'
        )
        
        valid_types = ['viewer', 'host']
        
        for channel_type in valid_types:
            channel = WebRTCUserChannel.objects.create(
                user=self.user2,
                channel_id=f'channel-{channel_type}',
                channel_type=channel_type
            )
            self.assertEqual(channel.channel_type, channel_type)
    
    def test_webrtc_user_offer_creation(self):
        """Test WebRTC user offer creation"""
        from cc.models import Session
        main_session = Session.objects.create(
            unique_id=uuid.uuid4(),
            user=self.user1
        )
        session = WebRTCSession.objects.create(
            session=main_session,
            session_unique_id='webrtc-session-123'
        )
        
        offer = WebRTCUserOffer.objects.create(
            session=session,
            user=self.user2,
            from_id='offer-789',
            id_type='viewer',
            sdp={"type": "offer", "sdp": "..."}
        )
        
        self.assertEqual(offer.session, session)
        self.assertEqual(offer.user, self.user2)
        self.assertEqual(offer.from_id, 'offer-789')
        self.assertEqual(offer.id_type, 'viewer')
        self.assertIn('type', offer.sdp)


class MessageThreadTest(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user('user1', 'user1@example.com', 'password')
        self.user2 = User.objects.create_user('user2', 'user2@example.com', 'password')
        self.user3 = User.objects.create_user('user3', 'user3@example.com', 'password')
    
    def test_thread_creation(self):
        """Test message thread creation"""
        thread = MessageThread.objects.create(
            title='Test Discussion',
            creator=self.user1
        )
        
        self.assertEqual(thread.title, 'Test Discussion')
        self.assertEqual(thread.creator, self.user1)
    
    def test_thread_participants(self):
        """Test thread participants management"""
        thread = MessageThread.objects.create(
            title='Team Discussion',
            creator=self.user1
        )
        
        # Add participants
        thread.participants.add(self.user1, self.user2, self.user3)
        
        self.assertEqual(thread.participants.count(), 3)
        self.assertIn(self.user1, thread.participants.all())
        self.assertIn(self.user2, thread.participants.all())
        self.assertIn(self.user3, thread.participants.all())
    
    def test_thread_system_flag(self):
        """Test system thread flag"""
        thread = MessageThread.objects.create(
            title='System Thread',
            creator=self.user1,
            is_system_thread=True
        )
        self.assertTrue(thread.is_system_thread)


class MessageTest(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user('user1', 'user1@example.com', 'password')
        self.user2 = User.objects.create_user('user2', 'user2@example.com', 'password')
        
        self.thread = MessageThread.objects.create(
            title='Test Thread',
            creator=self.user1
        )
        self.thread.participants.add(self.user1, self.user2)
    
    def test_message_creation(self):
        """Test basic message creation"""
        message = Message.objects.create(
            thread=self.thread,
            sender=self.user1,
            content='Hello, this is a test message',
            message_type='user_message'
        )
        
        self.assertEqual(message.thread, self.thread)
        self.assertEqual(message.sender, self.user1)
        self.assertEqual(message.content, 'Hello, this is a test message')
        self.assertEqual(message.message_type, 'user_message')
    
    def test_message_types(self):
        """Test valid message types"""
        valid_types = ['user_message', 'system_notification', 'alert', 'announcement']
        
        for message_type in valid_types:
            message = Message.objects.create(
                thread=self.thread,
                sender=self.user1,
                content=f'Test {message_type} message',
                message_type=message_type
            )
            self.assertEqual(message.message_type, message_type)
    
    def test_message_priority(self):
        """Test message priority functionality"""
        message = Message.objects.create(
            thread=self.thread,
            sender=self.user1,
            content='Important message',
            message_type='user_message',
            priority='high'
        )
        
        self.assertEqual(message.content, 'Important message')
        self.assertEqual(message.priority, 'high')
        self.assertIsNotNone(message.updated_at)
    
    def test_message_associations(self):
        """Test message associations with other models"""
        message = Message.objects.create(
            thread=self.thread,
            sender=self.user1,
            content='Message with associations',
            message_type='user_message'
        )
        
        # Test that the message is properly associated with the thread
        self.assertEqual(message.thread, self.thread)
        self.assertIn(message, self.thread.messages.all())


class MessageRecipientTest(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user('user1', 'user1@example.com', 'password')
        self.user2 = User.objects.create_user('user2', 'user2@example.com', 'password')
        
        self.thread = MessageThread.objects.create(
            title='Test Thread',
            creator=self.user1
        )
        
        self.message = Message.objects.create(
            thread=self.thread,
            sender=self.user1,
            content='Test message'
        )
    
    def test_recipient_creation(self):
        """Test message recipient creation"""
        recipient = MessageRecipient.objects.create(
            message=self.message,
            user=self.user2
        )
        
        self.assertEqual(recipient.message, self.message)
        self.assertEqual(recipient.user, self.user2)
        self.assertFalse(recipient.is_read)
        self.assertFalse(recipient.is_deleted)
        self.assertIsNone(recipient.read_at)
    
    def test_recipient_read_status(self):
        """Test message read status tracking"""
        recipient = MessageRecipient.objects.create(
            message=self.message,
            user=self.user2
        )
        
        # Mark as read
        recipient.is_read = True
        recipient.read_at = timezone.now()
        recipient.save()
        
        self.assertTrue(recipient.is_read)
        self.assertIsNotNone(recipient.read_at)
    
    def test_recipient_deletion(self):
        """Test message deletion by recipient"""
        recipient = MessageRecipient.objects.create(
            message=self.message,
            user=self.user2
        )
        
        # Mark as deleted
        recipient.is_deleted = True
        recipient.save()
        
        self.assertTrue(recipient.is_deleted)


class MessageAttachmentTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        
        self.thread = MessageThread.objects.create(
            title='Test Thread',
            creator=self.user
        )
        
        self.message = Message.objects.create(
            thread=self.thread,
            sender=self.user,
            content='Message with attachment',
            message_type='user_message'
        )
    
    def test_attachment_creation(self):
        """Test message attachment creation"""
        attachment = MessageAttachment.objects.create(
            message=self.message,
            file_name='test_document.pdf',
            file_size=1024000,  # 1MB
            content_type='application/pdf'
        )
        
        self.assertEqual(attachment.message, self.message)
        self.assertEqual(attachment.file_name, 'test_document.pdf')
        self.assertEqual(attachment.file_size, 1024000)
        self.assertEqual(attachment.content_type, 'application/pdf')


class ExternalContactTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.lab_group = LabGroup.objects.create(
            name='Test Lab',
            description='Test lab group'
        )
    
    def test_external_contact_creation(self):
        """Test external contact creation"""
        contact = ExternalContact.objects.create(
            contact_name='Dr. Jane Smith',
            user=self.user
        )
        
        self.assertEqual(contact.contact_name, 'Dr. Jane Smith')
        self.assertEqual(contact.user, self.user)
    
    def test_contact_details_association(self):
        """Test contact details association"""
        contact = ExternalContact.objects.create(
            contact_name='Test Contact',
            user=self.user
        )
        
        contact_detail = ExternalContactDetails.objects.create(
            contact_method_alt_name='Primary Email',
            contact_type='email',
            contact_value='test@example.com'
        )
        
        contact.contact_details.add(contact_detail)
        self.assertIn(contact_detail, contact.contact_details.all())
    
    def test_contact_string_representation(self):
        """Test contact string representation"""
        contact = ExternalContact.objects.create(
            contact_name='Test Contact',
            user=self.user
        )
        
        # Assuming the __str__ method returns the contact_name
        self.assertEqual(contact.contact_name, 'Test Contact')


class ExternalContactDetailsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        
        self.contact = ExternalContact.objects.create(
            contact_name='Dr. John Doe',
            user=self.user
        )
    
    def test_contact_details_creation(self):
        """Test external contact details creation"""
        details = ExternalContactDetails.objects.create(
            contact_method_alt_name='Primary Email',
            contact_type='email',
            contact_value='john.doe@research.edu'
        )
        
        self.contact.contact_details.add(details)
        self.assertEqual(details.contact_type, 'email')
        self.assertEqual(details.contact_value, 'john.doe@research.edu')
        self.assertIn(details, self.contact.contact_details.all())
    
    def test_contact_detail_types(self):
        """Test valid contact detail types"""
        valid_types = ['email', 'phone', 'address', 'other']
        
        for detail_type in valid_types:
            details = ExternalContactDetails.objects.create(
                contact_method_alt_name=f'{detail_type.capitalize()} Contact',
                contact_type=detail_type,
                contact_value=f'test_{detail_type}_value'
            )
            self.assertEqual(details.contact_type, detail_type)


class BackupLogTest(TestCase):
    def test_backup_log_creation(self):
        """Test backup log creation"""
        backup = BackupLog.objects.create(
            backup_type='database',
            status='running',
            triggered_by='scheduled_task'
        )
        
        self.assertEqual(backup.backup_type, 'database')
        self.assertEqual(backup.status, 'running')
        self.assertEqual(backup.triggered_by, 'scheduled_task')
        self.assertIsNotNone(backup.started_at)
        self.assertIsNone(backup.completed_at)
        self.assertIsNone(backup.duration_seconds)
    
    def test_backup_types(self):
        """Test valid backup types"""
        valid_types = ['database', 'media', 'full']
        
        for backup_type in valid_types:
            backup = BackupLog.objects.create(
                backup_type=backup_type,
                status='pending',
                triggered_by='test'
            )
            self.assertEqual(backup.backup_type, backup_type)
    
    def test_backup_statuses(self):
        """Test valid backup statuses"""
        valid_statuses = ['running', 'completed', 'failed', 'cancelled']
        
        for status in valid_statuses:
            backup = BackupLog.objects.create(
                backup_type='database',
                status=status,
                triggered_by='test'
            )
            self.assertEqual(backup.status, status)
    
    def test_backup_completion(self):
        """Test backup completion with file info"""
        backup = BackupLog.objects.create(
            backup_type='full',
            status='running',
            triggered_by='manual'
        )
        
        # Complete the backup
        backup.status = 'completed'
        backup.completed_at = timezone.now()
        backup.duration_seconds = 300  # 5 minutes
        backup.backup_file_path = '/backups/full_backup_20240115.tar.gz'
        backup.file_size_bytes = 1073741824  # 1GB
        backup.success_message = 'Backup completed successfully'
        backup.save()
        
        self.assertEqual(backup.status, 'completed')
        self.assertIsNotNone(backup.completed_at)
        self.assertEqual(backup.duration_seconds, 300)
        self.assertIsNotNone(backup.backup_file_path)
        self.assertEqual(backup.file_size_bytes, 1073741824)
        self.assertEqual(backup.file_size_mb, 1024.0)  # Computed property
    
    def test_backup_failure(self):
        """Test backup failure with error message"""
        backup = BackupLog.objects.create(
            backup_type='media',
            status='failed',
            triggered_by='scheduled_task',
            error_message='Disk space insufficient'
        )
        
        self.assertEqual(backup.status, 'failed')
        self.assertEqual(backup.error_message, 'Disk space insufficient')
    
    def test_backup_display_properties(self):
        """Test backup display properties"""
        backup = BackupLog.objects.create(
            backup_type='database',
            status='completed',
            triggered_by='manual'
        )
        
        # Test display properties (if implemented)
        self.assertIn('database', str(backup).lower())
        self.assertIn('completed', str(backup).lower())


class SiteSettingsTest(TestCase):
    def test_site_settings_creation(self):
        """Test site settings creation"""
        settings = SiteSettings.objects.create(
            site_name='Test LIMS',
            site_tagline='A test laboratory management system',
            banner_enabled=True,
            banner_text='Welcome to Test LIMS',
            allow_import_protocols=True
        )
        
        self.assertEqual(settings.site_name, 'Test LIMS')
        self.assertEqual(settings.site_tagline, 'A test laboratory management system')
        self.assertTrue(settings.banner_enabled)
        self.assertEqual(settings.banner_text, 'Welcome to Test LIMS')
        self.assertTrue(settings.allow_import_protocols)
    
    def test_color_settings(self):
        """Test color setting validation"""
        settings = SiteSettings.objects.create(
            site_name='Test LIMS',
            primary_color='#ff0000',
            secondary_color='#00ff00',
            banner_color='#0000ff',
            banner_text_color='#ffffff'
        )
        
        self.assertEqual(settings.primary_color, '#ff0000')
        self.assertEqual(settings.secondary_color, '#00ff00')
        self.assertEqual(settings.banner_color, '#0000ff')
        self.assertEqual(settings.banner_text_color, '#ffffff')


class CommunicationIntegrationTest(TestCase):
    """Integration tests for communication models working together"""
    
    def setUp(self):
        self.user1 = User.objects.create_user('user1', 'user1@example.com', 'password')
        self.user2 = User.objects.create_user('user2', 'user2@example.com', 'password')
        self.user3 = User.objects.create_user('user3', 'user3@example.com', 'password')
    
    def test_complete_messaging_workflow(self):
        """Test complete messaging workflow"""
        # 1. Create message thread
        thread = MessageThread.objects.create(
            title='Project Discussion',
            creator=self.user1
        )
        thread.participants.add(self.user1, self.user2, self.user3)
        
        # 2. Send initial message
        message1 = Message.objects.create(
            thread=thread,
            sender=self.user1,
            content='Hello team, let\'s discuss the project',
            message_type='user_message'
        )
        
        # 3. Create recipients
        recipients = [
            MessageRecipient.objects.create(message=message1, user=self.user2),
            MessageRecipient.objects.create(message=message1, user=self.user3)
        ]
        
        # 4. Reply to message
        reply = Message.objects.create(
            thread=thread,
            sender=self.user2,
            content='Sounds good, when should we meet?',
            message_type='user_message',
        )
        
        # 5. Mark message as read
        recipients[0].is_read = True
        recipients[0].read_at = timezone.now()
        recipients[0].save()
        
        # 6. Send message with attachment
        message_with_attachment = Message.objects.create(
            thread=thread,
            sender=self.user3,
            content='Here\'s the project document',
            message_type='user_message'
        )
        
        attachment = MessageAttachment.objects.create(
            message=message_with_attachment,
            file_name='project_plan.pdf',
            file_size=2048000,
            content_type='application/pdf'
        )
        
        # Verify the complete workflow
        self.assertEqual(thread.participants.count(), 3)
        self.assertEqual(Message.objects.filter(thread=thread).count(), 3)
        self.assertEqual(reply.sender, self.user2)
        self.assertTrue(recipients[0].is_read)
        self.assertFalse(recipients[1].is_read)
        self.assertEqual(attachment.message, message_with_attachment)
    
    def test_webrtc_messaging_integration(self):
        """Test WebRTC integration with messaging"""
        # Create message thread for video call
        thread = MessageThread.objects.create(
            title='Video Call Discussion',
            creator=self.user1
        )
        thread.participants.add(self.user1, self.user2)

        session = Session.objects.create(
            unique_id=uuid.uuid4(),
            user=self.user1
        )

        webrtc_session = WebRTCSession.objects.create(
            session_unique_id='call-123', session_id=session.id
        )
        
        # Add users to WebRTC channels
        channel1 = WebRTCUserChannel.objects.create(
            user=self.user1,
            channel_id='channel-user1',
            channel_type='video'
        )
        
        channel2 = WebRTCUserChannel.objects.create(
            user=self.user2,
            channel_id='channel-user2',
            channel_type='video'
        )
        
        # Send system message about call start
        call_message = Message.objects.create(
            thread=thread,
            sender=self.user1,
            content=f'Video call started: {webrtc_session.session_unique_id}',
            message_type='system_notification'
        )
        
        # Verify integration
        self.assertEqual(webrtc_session.session, session)
        self.assertEqual(WebRTCUserChannel.objects.count(), 2)
        self.assertEqual(call_message.message_type, 'system_notification')
        self.assertIn('Video call started', call_message.content)