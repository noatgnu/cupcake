"""
Comprehensive validation tests for CUPCAKE models
Focuses on field validation, constraints, and business logic
"""
import uuid
import tempfile
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch, Mock
from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from cc.models import (
    Annotation, AnnotationFolder, StorageObject, StoredReagent,
    Reagent, ProtocolReagent, StepReagent, Tag, ProtocolTag, StepTag,
    RemoteHost, InstrumentUsage, InstrumentPermission, TimeKeeper,
    WebRTCSession, WebRTCUserChannel, WebRTCUserOffer, StepVariation,
    Project, ProtocolModel, ProtocolStep, Session, Instrument, InstrumentJob
)


class AnnotationValidationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.project = Project.objects.create(project_name='Test Project')
        self.protocol = ProtocolModel.objects.create(
            protocol_title='Test Protocol',
            user=self.user
        )
        self.step = ProtocolStep.objects.create(
            protocol=self.protocol,
            step_title='Test Step',
            step_description='Test Description'
        )
        self.session = Session.objects.create(
            unique_id='test-session-123',
            user=self.user
        )
    
    def test_annotation_empty_name(self):
        """Test annotation with empty name"""
        with self.assertRaises(IntegrityError):
            Annotation.objects.create(
                step=self.step,
                session=self.session,
                user=self.user,
                annotation_name=''
            )
    
    def test_annotation_very_long_name(self):
        """Test annotation with very long name"""
        long_name = 'x' * 300  # Exceeds typical varchar limits
        with self.assertRaises(ValidationError):
            annotation = Annotation(
                step=self.step,
                session=self.session,
                user=self.user,
                annotation_name=long_name
            )
            annotation.full_clean()
    
    def test_annotation_large_data_content(self):
        """Test annotation with very large data content"""
        large_data = 'x' * 1000000  # 1MB of data
        annotation = Annotation.objects.create(
            step=self.step,
            session=self.session,
            user=self.user,
            annotation_name='Large Data Annotation',
            data=large_data
        )
        self.assertEqual(len(annotation.data), 1000000)
    
    def test_annotation_special_characters_in_data(self):
        """Test annotation with special characters and unicode"""
        special_data = '''
            Special chars: !@#$%^&*()_+-=[]{}|;':",./<>?
            Unicode: αβγ 中文 日本語 🧪
            HTML-like: <tag>content</tag>
            JSON-like: {"key": "value", "number": 123}
            SQL-like: SELECT * FROM table WHERE id = 1;
        '''
        annotation = Annotation.objects.create(
            step=self.step,
            session=self.session,
            user=self.user,
            annotation_name='Special Characters',
            data=special_data
        )
        self.assertIn('🧪', annotation.data)
        self.assertIn('SELECT', annotation.data)
    
    def test_annotation_boundary_annotation_types(self):
        """Test annotation with boundary annotation type values"""
        valid_types = [
            'audio', 'video', 'image', 'text', 'note', 'warning', 
            'error', 'success', 'transcription', 'translation', 'scratch'
        ]
        
        for annotation_type in valid_types:
            annotation = Annotation.objects.create(
                step=self.step,
                session=self.session,
                user=self.user,
                annotation_name=f'Test {annotation_type}',
                annotation_type=annotation_type
            )
            self.assertEqual(annotation.annotation_type, annotation_type)
    
    def test_annotation_invalid_type(self):
        """Test annotation with invalid type"""
        with self.assertRaises(ValidationError):
            annotation = Annotation(
                step=self.step,
                session=self.session,
                user=self.user,
                annotation_name='Invalid Type',
                annotation_type='invalid_type'
            )
            annotation.full_clean()
    
    def test_annotation_orphaned_references(self):
        """Test annotation behavior when referenced objects are deleted"""
        annotation = Annotation.objects.create(
            step=self.step,
            session=self.session,
            user=self.user,
            annotation_name='Test Annotation'
        )
        annotation_id = annotation.id
        
        # Delete step - annotation should be deleted (CASCADE)
        self.step.delete()
        
        with self.assertRaises(Annotation.DoesNotExist):
            Annotation.objects.get(id=annotation_id)


class StoredReagentValidationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.reagent = Reagent.objects.create(
            reagent_name='Test Reagent',
            reagent_description='Test Description'
        )
        self.storage = StorageObject.objects.create(
            object_name='Test Storage',
            object_type='freezer',
            user=self.user
        )
    
    def test_stored_reagent_negative_amount(self):
        """Test stored reagent with negative amount"""
        with self.assertRaises(ValidationError):
            stored_reagent = StoredReagent(
                reagent=self.reagent,
                storage_object=self.storage,
                amount=-10.5,
                user=self.user
            )
            stored_reagent.full_clean()
    
    def test_stored_reagent_zero_amount(self):
        """Test stored reagent with zero amount (empty container)"""
        stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent,
            storage_object=self.storage,
            amount=0.0,
            user=self.user
        )
        self.assertEqual(stored_reagent.amount, 0.0)
    
    def test_stored_reagent_very_large_amount(self):
        """Test stored reagent with very large amount"""
        large_amount = 999999999.99
        stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent,
            storage_object=self.storage,
            amount=large_amount,
            user=self.user
        )
        self.assertEqual(stored_reagent.amount, large_amount)
    
    def test_stored_reagent_high_precision_amount(self):
        """Test stored reagent with high precision decimal amount"""
        precise_amount = 123.456789
        stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent,
            storage_object=self.storage,
            amount=precise_amount,
            user=self.user
        )
        # Should handle precision according to FloatField definition
        self.assertAlmostEqual(stored_reagent.amount, precise_amount, places=5)
    
    def test_stored_reagent_invalid_barcode_format(self):
        """Test stored reagent with various barcode formats"""
        # Test very long barcode
        long_barcode = '1' * 200
        stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent,
            storage_object=self.storage,
            amount=10.0,
            barcode=long_barcode,
            user=self.user
        )
        self.assertEqual(stored_reagent.barcode, long_barcode)
        
        # Test barcode with special characters
        special_barcode = 'ABC-123_XYZ.456@789'
        stored_reagent2 = StoredReagent.objects.create(
            reagent=self.reagent,
            storage_object=self.storage,
            amount=15.0,
            barcode=special_barcode,
            user=self.user
        )
        self.assertEqual(stored_reagent2.barcode, special_barcode)
    
    def test_stored_reagent_duplicate_barcode(self):
        """Test stored reagent with duplicate barcode"""
        barcode = 'DUPLICATE-123'
        
        StoredReagent.objects.create(
            reagent=self.reagent,
            storage_object=self.storage,
            amount=10.0,
            barcode=barcode,
            user=self.user
        )
        
        # Should allow duplicate barcodes if no unique constraint
        stored_reagent2 = StoredReagent.objects.create(
            reagent=self.reagent,
            storage_object=self.storage,
            amount=20.0,
            barcode=barcode,
            user=self.user
        )
        
        duplicates = StoredReagent.objects.filter(barcode=barcode)
        self.assertEqual(duplicates.count(), 2)


class RemoteHostValidationTest(TestCase):
    def test_remote_host_invalid_url_format(self):
        """Test remote host with invalid URL formats"""
        invalid_urls = [
            'not-a-url',
            'ftp://invalid-protocol.com',
            'http://',
            'https://',
            'http://space in url.com',
            'http://中文.com'  # Unicode domain
        ]
        
        for invalid_url in invalid_urls:
            with self.subTest(url=invalid_url):
                with self.assertRaises(ValidationError):
                    remote_host = RemoteHost(
                        host_name='Test Host',
                        host_url=invalid_url
                    )
                    remote_host.full_clean()
    
    def test_remote_host_valid_url_formats(self):
        """Test remote host with valid URL formats"""
        valid_urls = [
            'https://example.com',
            'http://localhost:8000',
            'https://sub.domain.co.uk',
            'http://192.168.1.1:3000',
            'https://api.service.com/v1'
        ]
        
        for valid_url in valid_urls:
            with self.subTest(url=valid_url):
                remote_host = RemoteHost.objects.create(
                    host_name=f'Host for {valid_url}',
                    host_url=valid_url
                )
                self.assertEqual(remote_host.host_url, valid_url)
    
    def test_remote_host_very_long_token(self):
        """Test remote host with very long host token"""
        long_token = 'x' * 1000  # Very long token
        remote_host = RemoteHost.objects.create(
            host_name='Long Token Host',
            host_url='https://example.com',
            host_token=long_token
        )
        self.assertEqual(remote_host.host_token, long_token)
    
    def test_remote_host_special_characters_in_token(self):
        """Test remote host with special characters in token"""
        special_token = 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiYWRtaW4iOnRydWV9'
        remote_host = RemoteHost.objects.create(
            host_name='JWT Token Host',
            host_url='https://api.example.com',
            host_token=special_token
        )
        self.assertEqual(remote_host.host_token, special_token)


class SessionValidationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
    
    def test_session_empty_unique_id(self):
        """Test session with empty unique_id"""
        with self.assertRaises(IntegrityError):
            Session.objects.create(
                unique_id='',
                user=self.user
            )
    
    def test_session_very_long_unique_id(self):
        """Test session with very long unique_id"""
        long_id = 'x' * 300
        with self.assertRaises(ValidationError):
            session = Session(
                unique_id=long_id,
                user=self.user
            )
            session.full_clean()
    
    def test_session_duplicate_unique_id(self):
        """Test session with duplicate unique_id"""
        unique_id = 'duplicate-session-id'
        
        Session.objects.create(
            unique_id=unique_id,
            user=self.user
        )
        
        with self.assertRaises(IntegrityError):
            Session.objects.create(
                unique_id=unique_id,
                user=self.user
            )
    
    def test_session_special_characters_unique_id(self):
        """Test session with special characters in unique_id"""
        special_ids = [
            'session-123_ABC',
            'session.with.dots',
            'session@symbol#123',
            'session with spaces',  # Might not be allowed
            'sessión-unicode',
        ]
        
        for special_id in special_ids:
            with self.subTest(unique_id=special_id):
                try:
                    session = Session.objects.create(
                        unique_id=special_id,
                        user=self.user
                    )
                    self.assertEqual(session.unique_id, special_id)
                except (ValidationError, IntegrityError):
                    # Some special characters might not be allowed
                    pass
    
    def test_session_name_boundary_values(self):
        """Test session with boundary name values"""
        # Very long name
        long_name = 'Session Name ' * 50  # Very long name
        session = Session.objects.create(
            unique_id='long-name-session',
            user=self.user,
            name=long_name
        )
        self.assertEqual(session.name, long_name)
        
        # Empty name (should be allowed)
        session2 = Session.objects.create(
            unique_id='empty-name-session',
            user=self.user,
            name=''
        )
        self.assertEqual(session2.name, '')


class TimeKeeperValidationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.session = Session.objects.create(
            unique_id='test-session',
            user=self.user
        )
    
    def test_timekeeper_negative_duration(self):
        """Test timekeeper with negative duration"""
        with self.assertRaises(ValidationError):
            timekeeper = TimeKeeper(
                session=self.session,
                current_duration=-10.5,
                started=False
            )
            timekeeper.full_clean()
    
    def test_timekeeper_zero_duration(self):
        """Test timekeeper with zero duration"""
        timekeeper = TimeKeeper.objects.create(
            session=self.session,
            current_duration=0.0,
            started=False
        )
        self.assertEqual(timekeeper.current_duration, 0.0)
    
    def test_timekeeper_very_large_duration(self):
        """Test timekeeper with very large duration (years)"""
        large_duration = 365 * 24 * 3600.0  # One year in seconds
        timekeeper = TimeKeeper.objects.create(
            session=self.session,
            current_duration=large_duration,
            started=False
        )
        self.assertEqual(timekeeper.current_duration, large_duration)
    
    def test_timekeeper_high_precision_duration(self):
        """Test timekeeper with high precision duration"""
        precise_duration = 123.456789
        timekeeper = TimeKeeper.objects.create(
            session=self.session,
            current_duration=precise_duration,
            started=True
        )
        self.assertAlmostEqual(timekeeper.current_duration, precise_duration, places=5)


class WebRTCValidationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
    
    def test_webrtc_session_boundary_values(self):
        """Test WebRTC session with boundary session ID values"""
        # Very long session ID
        long_session_id = 'x' * 500
        session = WebRTCSession.objects.create(
            session_id=long_session_id,
            user=self.user
        )
        self.assertEqual(session.session_id, long_session_id)
        
        # Session ID with special characters
        special_session_id = 'session-123_ABC@456#789'
        session2 = WebRTCSession.objects.create(
            session_id=special_session_id,
            user=self.user
        )
        self.assertEqual(session2.session_id, special_session_id)
    
    def test_webrtc_user_offer_large_offer_data(self):
        """Test WebRTC user offer with large offer data"""
        session = WebRTCSession.objects.create(
            session_id='test-session',
            user=self.user
        )
        
        # Very large offer data (simulating complex SDP)
        large_offer_data = 'v=0\r\n' + 'a=candidate:' + 'x' * 10000
        
        offer = WebRTCUserOffer.objects.create(
            session=session,
            user=self.user,
            offer_data=large_offer_data
        )
        self.assertEqual(len(offer.offer_data), len(large_offer_data))
    
    def test_webrtc_channel_invalid_type(self):
        """Test WebRTC channel with invalid channel type"""
        session = WebRTCSession.objects.create(
            session_id='test-session',
            user=self.user
        )
        
        with self.assertRaises(ValidationError):
            channel = WebRTCUserChannel(
                session=session,
                user=self.user,
                channel_type='invalid_type'
            )
            channel.full_clean()


class TagValidationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.protocol = ProtocolModel.objects.create(
            protocol_title='Test Protocol',
            user=self.user
        )
        self.step = ProtocolStep.objects.create(
            protocol=self.protocol,
            step_title='Test Step',
            step_description='Test Description'
        )
    
    def test_tag_empty_name(self):
        """Test tag with empty name"""
        with self.assertRaises(IntegrityError):
            Tag.objects.create(tag_name='')
    
    def test_tag_very_long_name(self):
        """Test tag with very long name"""
        long_name = 'x' * 300
        with self.assertRaises(ValidationError):
            tag = Tag(tag_name=long_name)
            tag.full_clean()
    
    def test_tag_duplicate_name(self):
        """Test tag with duplicate name"""
        tag_name = 'Duplicate Tag'
        
        Tag.objects.create(tag_name=tag_name)
        
        # Should allow duplicate tag names if no unique constraint
        tag2 = Tag.objects.create(tag_name=tag_name)
        
        tags = Tag.objects.filter(tag_name=tag_name)
        self.assertEqual(tags.count(), 2)
    
    def test_tag_special_characters(self):
        """Test tag with special characters and unicode"""
        special_tags = [
            'Tag with spaces',
            'tag-with-hyphens',
            'tag_with_underscores',
            'tag.with.dots',
            'tag#with@symbols',
            'tagüwithüunicode',
            '中文标签',
            '🧪 emoji tag'
        ]
        
        for tag_name in special_tags:
            with self.subTest(tag_name=tag_name):
                tag = Tag.objects.create(tag_name=tag_name)
                self.assertEqual(tag.tag_name, tag_name)
    
    def test_protocol_tag_relationship(self):
        """Test protocol tag with various tag relationships"""
        tag = Tag.objects.create(tag_name='Test Tag')
        
        protocol_tag = ProtocolTag.objects.create(
            protocol=self.protocol,
            tag=tag
        )
        
        self.assertEqual(protocol_tag.protocol, self.protocol)
        self.assertEqual(protocol_tag.tag, tag)
    
    def test_step_tag_relationship(self):
        """Test step tag with various tag relationships"""
        tag = Tag.objects.create(tag_name='Step Tag')
        
        step_tag = StepTag.objects.create(
            step=self.step,
            tag=tag
        )
        
        self.assertEqual(step_tag.step, self.step)
        self.assertEqual(step_tag.tag, tag)


class ModelConstraintTest(TestCase):
    """Test database constraints and integrity rules"""
    
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.project = Project.objects.create(project_name='Test Project')
    
    def test_foreign_key_constraint_violation(self):
        """Test foreign key constraint violations"""
        # Try to create object with non-existent foreign key
        with self.assertRaises((IntegrityError, ValidationError)):
            # This should fail due to foreign key constraint
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO cc_protocolmodel (protocol_title, user_id) VALUES (%s, %s)",
                    ['Test Protocol', 99999]  # Non-existent user ID
                )
    
    def test_unique_constraint_violation(self):
        """Test unique constraint violations"""
        # Create session with unique_id
        unique_id = 'unique-session-123'
        Session.objects.create(
            unique_id=unique_id,
            user=self.user
        )
        
        # Try to create another session with same unique_id
        with self.assertRaises(IntegrityError):
            Session.objects.create(
                unique_id=unique_id,
                user=self.user
            )
    
    def test_not_null_constraint_violation(self):
        """Test NOT NULL constraint violations"""
        with self.assertRaises((IntegrityError, ValidationError)):
            # Try to create protocol without required title
            ProtocolModel.objects.create(
                protocol_title=None,  # Should violate NOT NULL
                user=self.user
            )
    
    def test_check_constraint_validation(self):
        """Test custom check constraints if any exist"""
        # This would test custom database CHECK constraints
        # Example: rating values between 0 and 10
        protocol = ProtocolModel.objects.create(
            protocol_title='Test Protocol',
            user=self.user
        )
        
        # This should be caught by model validation before DB
        with self.assertRaises(ValueError):
            ProtocolRating.objects.create(
                protocol=protocol,
                user=self.user,
                complexity_rating=-5,  # Invalid rating
                duration_rating=5
            )
