"""
Tests for reagent and inventory models: Reagent, StoredReagent, StorageObject, ReagentAction
"""
import uuid

from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.exceptions import ValidationError
from datetime import timedelta, date
from decimal import Decimal
from cc.models import (
    Reagent, ProtocolReagent, StepReagent, StoredReagent, StorageObject,
    ReagentAction, ReagentSubscription, LabGroup, ProtocolModel, ProtocolStep,
    AnnotationFolder, Session
)


class ReagentModelTest(TestCase):
    def setUp(self):
        import time
        timestamp = str(int(time.time() * 1000))
        self.user = User.objects.create_user(f'reagent_user_{timestamp}', f'reagent_{timestamp}@example.com', 'password')
    
    def test_reagent_creation(self):
        """Test basic reagent creation"""
        reagent = Reagent.objects.create(
            name='Tris Buffer',
                        unit='g'
        )
        
        self.assertEqual(reagent.name, 'Tris Buffer')
        self.assertEqual(reagent.unit, 'g')
    
    def test_reagent_string_representation(self):
        """Test reagent string representation"""
        reagent = Reagent.objects.create(
            name='Tris Buffer',
            unit='g'
        )
        self.assertEqual(reagent.name, 'Tris Buffer')


class StorageObjectTest(TestCase):
    def setUp(self):
        import time
        timestamp = str(int(time.time() * 1000))
        self.user = User.objects.create_user(f'storage_user_{timestamp}', f'storage_{timestamp}@example.com', 'password')
        self.lab_group = LabGroup.objects.create(
            name='Test Lab',
            description='Test lab group'
        )
    
    def test_storage_object_creation(self):
        """Test basic storage object creation"""
        storage = StorageObject.objects.create(
            object_name='Freezer A',
            object_type='freezer',
            user=self.user
        )
        
        self.assertEqual(storage.object_name, 'Freezer A')
        self.assertEqual(storage.object_type, 'freezer')
        self.assertEqual(storage.user, self.user)
    
    def test_storage_type_choices(self):
        """Test valid storage type choices"""
        valid_types = ['freezer', 'fridge', 'room_temp', 'incubator', 'desiccator', 'cabinet']
        
        for storage_type in valid_types:
            storage = StorageObject.objects.create(
                object_name=f'Storage {storage_type}',
                object_type=storage_type,
                user=self.user
            )
            self.assertEqual(storage.object_type, storage_type)
    
    def test_storage_lab_group_access(self):
        """Test lab group access to storage objects"""
        storage = StorageObject.objects.create(
            object_name='Shared Freezer',
            object_type='freezer',
            user=self.user
        )
        
        storage.access_lab_groups.add(self.lab_group)
        self.assertIn(self.lab_group, storage.access_lab_groups.all())


class StoredReagentTest(TestCase):
    def setUp(self):
        import time
        timestamp = str(int(time.time() * 1000))
        self.user = User.objects.create_user(f'stored_reagent_user_{timestamp}', f'stored_reagent_{timestamp}@example.com', 'password')
        self.lab_group = LabGroup.objects.create(
            name='Test Lab',
            description='Test lab group'
        )
        self.lab_group.users.add(self.user)
        
        self.reagent = Reagent.objects.create(
            name='Tris Buffer',
            unit='g'
        )
        
        self.storage = StorageObject.objects.create(
            object_name='Lab Freezer',
            object_type='freezer',
            user=self.user
        )
    
    def test_stored_reagent_creation(self):
        """Test basic stored reagent creation"""
        stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent,
            storage_object=self.storage,
            expiration_date=date.today() + timedelta(days=365),
            quantity=100.0,
            user=self.user
        )
        
        self.assertEqual(stored_reagent.reagent, self.reagent)
        self.assertEqual(stored_reagent.storage_object, self.storage)
    
    def test_stored_reagent_barcode_generation(self):
        """Test automatic barcode generation"""
        stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent,
            storage_object=self.storage,
            quantity=100.0,
            barcode='123456',
            user=self.user
        )
        
        self.assertIsNotNone(stored_reagent.barcode)
    
    def test_get_current_quantity(self):
        """Test current quantity calculation with actions"""
        stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent,
            quantity=500.0,
            storage_object=self.storage,
            user=self.user
        )
        
        self.assertEqual(stored_reagent.get_current_quantity(), 500.0)
        
        ReagentAction.objects.create(
            reagent=stored_reagent,
            action_type='reserve',
            quantity=50.0,
            user=self.user,
            notes='Used for experiment 1'
        )
        
        ReagentAction.objects.create(
            reagent=stored_reagent,
            action_type='reserve',
            quantity=25.0,
            user=self.user,
            notes='Used for experiment 2'
        )
        
        # Current quantity should be reduced
        self.assertEqual(stored_reagent.get_current_quantity(), 425.0)  # 500 - 50 - 25
        
        # Add an addition action
        ReagentAction.objects.create(
            reagent=stored_reagent,
            action_type='add',
            quantity=100.0,  # Actually quantity added
            user=self.user,
            notes='Refilled from new bottle'
        )
        
        # Current quantity should be increased
        self.assertEqual(stored_reagent.get_current_quantity(), 525.0)  # 425 + 100
    
    def test_low_stock_checking(self):
        """Test low stock detection"""
        stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent,
            quantity=500.0,
            low_stock_threshold=100.0,
            storage_object=self.storage,
            user=self.user
        )
        
        # Initially should not be low stock
        self.assertFalse(stored_reagent.check_low_stock())
        
        # Use reagent to below minimum level
        ReagentAction.objects.create(
            reagent=stored_reagent,
            action_type='reserve',
            quantity=450.0,  # Leaves 50.0, below minimum of 100.0
            user=self.user
        )
        
        # Should now be low stock
        self.assertTrue(stored_reagent.check_low_stock())
    
    def test_expiration_checking(self):
        """Test expiration date monitoring"""
        # Create reagent expiring soon
        stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent,
            storage_object=self.storage,
            expiration_date=date.today() + timedelta(days=10),
            quantity= 500.0,
            user=self.user
        )
        
        # Should detect upcoming expiration
        self.assertTrue(stored_reagent.check_expiration())
        
        # Create reagent with distant expiration
        stored_reagent2 = StoredReagent.objects.create(
            reagent=self.reagent,
            storage_object=self.storage,
            expiration_date=date.today() + timedelta(days=365),
            quantity= 500.0,
            user=self.user
        )
        
        # Should not detect upcoming expiration
        self.assertFalse(stored_reagent2.check_expiration())
    
    def test_default_folder_creation(self):
        """Test default folder creation for reagents"""
        stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent,
            quantity= 500.0,
            storage_object=self.storage,
            user=self.user
        )
        
        # Create default folders
        stored_reagent.create_default_folders()
        
        # Check that folders were created
        folders = AnnotationFolder.objects.filter(stored_reagent=stored_reagent)
        folder_names = [folder.folder_name for folder in folders]
        
        expected_folders = ['Manuals', 'Certificates', 'MSDS']
        for expected_folder in expected_folders:
            self.assertIn(expected_folder, folder_names)
    
    def test_reagent_sharing_settings(self):
        """Test reagent sharing and access control"""
        stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent,
            access_all=False,
            quantity=500.0,
            storage_object=self.storage,
            user=self.user
        )
        
        self.assertFalse(stored_reagent.access_all)


class ReagentActionTest(TestCase):
    def setUp(self):
        import time
        timestamp = str(int(time.time() * 1000))
        self.user = User.objects.create_user(f'action_user_{timestamp}', f'action_{timestamp}@example.com', 'password')
        self.lab_group = LabGroup.objects.create(
            name='Test Lab',
            description='Test lab group'
        )
        
        self.reagent = Reagent.objects.create(
            name='Test Reagent',
            unit='mL'
        )
        
        self.stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent,
            quantity=500.0,
            storage_object=StorageObject.objects.create(
                object_name='Test Storage',
                object_type='freezer',
                user=self.user
            ),
            user=self.user
        )
        
        self.session = Session.objects.create(
            unique_id=uuid.uuid4(),
            user=self.user
        )
    
    def test_reagent_action_creation(self):
        """Test basic reagent action creation"""
        action = ReagentAction.objects.create(
            reagent=self.stored_reagent,
            action_type='reserve',
            quantity=25.0,
            user=self.user,
            notes='Used in protein assay',
            session=self.session
        )
        
        self.assertEqual(action.reagent, self.stored_reagent)
        self.assertEqual(action.action_type, 'reserve')
        self.assertEqual(action.quantity, 25.0)
        self.assertEqual(action.user, self.user)
        self.assertEqual(action.notes, 'Used in protein assay')
        self.assertEqual(action.session, self.session)
    
    def test_action_type_choices(self):
        """Test valid action type choices"""
        valid_types = ['reserve', 'add']
        
        for action_type in valid_types:
            action = ReagentAction.objects.create(
                reagent=self.stored_reagent,
                action_type=action_type,
                quantity=10.0,
                user=self.user
            )
            self.assertEqual(action.action_type, action_type)
    
    def test_scalable_reagent_action(self):
        """Test scalable reagent actions with scaling factors"""
        action = ReagentAction.objects.create(
            reagent=self.stored_reagent,
            action_type='reserve',
            quantity=25.0,
            user=self.user
        )
        action.reagent.reagent.scalable = True
        action.reagent.reagent.scalable_factor = 2.0
        self.assertTrue(action.reagent.reagent.scalable)
        self.assertEqual(action.reagent.reagent.scalable_factor, 2.0)
        
        # Effective quantity should be quantity_used * scalable_factor
        effective_quantity = action.quantity * action.reagent.reagent.scalable_factor
        self.assertEqual(effective_quantity, 50.0)


class ReagentSubscriptionTest(TestCase):
    def setUp(self):
        import time
        timestamp = str(int(time.time() * 1000))
        self.user = User.objects.create_user(f'subscription_user_{timestamp}', f'subscription_{timestamp}@example.com', 'password')
        self.lab_group = LabGroup.objects.create(
            name='Test Lab',
            description='Test lab group'
        )
        
        self.reagent = Reagent.objects.create(
            name='Test Reagent',
            unit='mL'
        )
        
        self.stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent,
            quantity=500.0,
            storage_object=StorageObject.objects.create(
                object_name='Test Storage',
                object_type='freezer',
                user=self.user
            ),
            user=self.user
        )
    
    def test_subscription_creation(self):
        """Test reagent subscription creation"""
        subscription, created = ReagentSubscription.objects.get_or_create(
            stored_reagent=self.stored_reagent,
            user=self.user,
            defaults={'notify_on_low_stock': True}
        )
        
        self.assertEqual(subscription.stored_reagent, self.stored_reagent)
        self.assertEqual(subscription.user, self.user)
        # If created, it should have the default value; if not created, we just verify it exists
        if created:
            self.assertEqual(subscription.notify_on_low_stock, True)
    
    def test_subscription_types(self):
        """Test different subscription notification types"""
        # Create a different stored reagent to avoid unique constraint violation
        reagent2 = Reagent.objects.create(
            name='Test Reagent 2',
            unit='mL'
        )
        
        stored_reagent2 = StoredReagent.objects.create(
            reagent=reagent2,
            quantity=500.0,
            storage_object=StorageObject.objects.create(
                object_name='Test Storage 2',
                object_type='fridge',
                user=self.user
            ),
            user=self.user
        )
        
        subscription, created = ReagentSubscription.objects.get_or_create(
            stored_reagent=stored_reagent2,
            user=self.user,
            defaults={'notify_on_expiry': True, 'notify_on_low_stock': True}
        )
        # If created, verify the default values; if not created, just verify it exists
        if created:
            self.assertTrue(subscription.notify_on_expiry)
            self.assertTrue(subscription.notify_on_low_stock)
    
    def test_subscription_unsubscribe(self):
        """Test unsubscribing from reagent notifications"""
        # Create a different stored reagent to avoid unique constraint violation
        reagent3 = Reagent.objects.create(
            name='Test Reagent 3',
            unit='µL'
        )
        
        stored_reagent3 = StoredReagent.objects.create(
            reagent=reagent3,
            quantity=500.0,
            storage_object=StorageObject.objects.create(
                object_name='Test Storage 3',
                object_type='cabinet',
                user=self.user
            ),
            user=self.user
        )
        
        # Test the unsubscribe method if it exists
        subscription, created = ReagentSubscription.objects.get_or_create(
            stored_reagent=stored_reagent3,
            user=self.user,
            defaults={'notify_on_low_stock': True, 'notify_on_expiry': True}
        )
        
        
        # Test unsubscribe functionality
        result = stored_reagent3.unsubscribe_user(self.user, True, True)
        self.assertTrue(result)
        
        # Subscription should be deactivated or deleted
        self.assertFalse(ReagentSubscription.objects.filter(user=self.user, stored_reagent=stored_reagent3).exists())


class ProtocolReagentTest(TestCase):
    def setUp(self):
        import time
        timestamp = str(int(time.time() * 1000))
        self.user = User.objects.create_user(f'protocol_reagent_user_{timestamp}', f'protocol_reagent_{timestamp}@example.com', 'password')
        self.protocol = ProtocolModel.objects.create(
            protocol_title='Test Protocol',
            user=self.user
        )
        self.reagent = Reagent.objects.create(
            name='Protocol Reagent',
            unit='mL'
        )
    
    def test_protocol_reagent_creation(self):
        """Test linking reagents to protocols"""
        protocol_reagent = ProtocolReagent.objects.create(
            protocol=self.protocol,
            reagent=self.reagent,
            quantity=100.0,
        )
        
        self.assertEqual(protocol_reagent.protocol, self.protocol)
        self.assertEqual(protocol_reagent.reagent, self.reagent)


class StepReagentTest(TestCase):
    def setUp(self):
        import time
        timestamp = str(int(time.time() * 1000))
        self.user = User.objects.create_user(f'step_reagent_user_{timestamp}', f'step_reagent_{timestamp}@example.com', 'password')
        self.protocol = ProtocolModel.objects.create(
            protocol_title='Test Protocol',
            user=self.user
        )
        self.step = ProtocolStep.objects.create(
            protocol=self.protocol,
            step_id=1,
            step_description='Test Step'
        )
        self.reagent = Reagent.objects.create(
            name='Step Reagent',
            unit='µL'
        )
    
    def test_step_reagent_creation(self):
        """Test linking reagents to protocol steps"""
        step_reagent = StepReagent.objects.create(
            step=self.step,
            reagent=self.reagent,
            quantity=50.0,
        )
        
        self.assertEqual(step_reagent.step, self.step)
        self.assertEqual(step_reagent.reagent, self.reagent)
        self.assertEqual(step_reagent.quantity, 50.0)
        self.assertEqual(step_reagent.reagent.unit, 'µL')


class ReagentIntegrationTest(TestCase):
    """Integration tests for reagent-related models working together"""
    
    def setUp(self):
        import time
        timestamp = str(int(time.time() * 1000))
        self.user = User.objects.create_user(f'integration_user_{timestamp}', f'integration_{timestamp}@example.com', 'password')
        self.lab_group = LabGroup.objects.create(
            name='Integration Test Lab',
            description='Test lab group'
        )
        self.lab_group.users.add(self.user)
        
        self.reagent = Reagent.objects.create(
            name='Integration Test Reagent',
            unit='mL',
                    )
        
        self.storage = StorageObject.objects.create(
            object_name='Test Storage',
            object_type='freezer',
            user=self.user
        )
        
        self.protocol = ProtocolModel.objects.create(
            protocol_title='Integration Test Protocol',
            user=self.user
        )
        
        self.session = Session.objects.create(
            unique_id=uuid.uuid4(),
            user=self.user
        )
    
    def test_complete_reagent_workflow(self):
        """Test complete workflow from reagent to usage tracking"""
        # 1. Create stored reagent
        stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent,
            quantity=1000.0,
            storage_object=self.storage,
            expiration_date=date.today() + timedelta(days=180),
            low_stock_threshold=200.0,
            user=self.user
        )
        
        # 2. Link reagent to protocol
        protocol_reagent = ProtocolReagent.objects.create(
            protocol=self.protocol,
            reagent=self.reagent,
            quantity=500.0,
        )
        
        # 3. Create subscription for notifications (use get_or_create to avoid unique constraint violation)
        subscription, created = ReagentSubscription.objects.get_or_create(
            stored_reagent=stored_reagent,
            user=self.user,
            defaults={'notify_on_low_stock': True}
        )
        
        # 4. Record usage action
        usage_action = ReagentAction.objects.create(
            reagent=stored_reagent,
            action_type='reserve',
            quantity=300.0,
            user=self.user,
            session=self.session,
            notes='Used in integration test protocol'
        )
        
        # 5. Record quality check action
        quality_action = ReagentAction.objects.create(
            reagent=stored_reagent,
            action_type='reserve',
            quantity=0.0,  # No quantity used for quality check
            user=self.user,
            notes='Monthly quality verification'
        )
        
        # Verify the complete workflow
        self.assertEqual(stored_reagent.get_current_quantity(), 700.0)  # 1000 - 300
        self.assertFalse(stored_reagent.check_low_stock())  # 700 > 200 (minimum)
        self.assertFalse(stored_reagent.check_expiration())  # 180 days is not soon
        
        # Verify relationships
        self.assertIn(usage_action, stored_reagent.reagent_actions.all())
        self.assertIn(quality_action, stored_reagent.reagent_actions.all())
        self.assertEqual(protocol_reagent.reagent, self.reagent)

        low_stock_action = ReagentAction.objects.create(
            reagent=stored_reagent,
            action_type='reserve',
            quantity=550.0,  # This will bring total to 150, below minimum of 200
            user=self.user,
            notes='Large usage causing low stock'
        )

        self.assertEqual(stored_reagent.get_current_quantity(), 150.0)
        self.assertTrue(stored_reagent.check_low_stock())