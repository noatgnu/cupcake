"""
Tests for reagent and inventory models: Reagent, StoredReagent, StorageObject, ReagentAction
"""
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
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
    
    def test_reagent_creation(self):
        """Test basic reagent creation"""
        reagent = Reagent.objects.create(
            reagent_name='Tris Buffer',
            cas_number='77-86-1',
            molecular_formula='C4H11NO3',
            molecular_weight=121.14
        )
        
        self.assertEqual(reagent.reagent_name, 'Tris Buffer')
        self.assertEqual(reagent.cas_number, '77-86-1')
        self.assertEqual(reagent.molecular_formula, 'C4H11NO3')
        self.assertEqual(reagent.molecular_weight, 121.14)
    
    def test_reagent_string_representation(self):
        """Test reagent string representation"""
        reagent = Reagent.objects.create(
            reagent_name='Tris Buffer',
            cas_number='77-86-1'
        )
        self.assertEqual(str(reagent), 'Tris Buffer')


class StorageObjectTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.lab_group = LabGroup.objects.create(
            group_name='Test Lab',
            description='Test lab group'
        )
    
    def test_storage_object_creation(self):
        """Test basic storage object creation"""
        storage = StorageObject.objects.create(
            object_name='Freezer A',
            object_type='freezer',
            temperature=-80,
            location='Lab Room 101',
            user=self.user
        )
        
        self.assertEqual(storage.object_name, 'Freezer A')
        self.assertEqual(storage.object_type, 'freezer')
        self.assertEqual(storage.temperature, -80)
        self.assertEqual(storage.location, 'Lab Room 101')
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
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.lab_group = LabGroup.objects.create(
            group_name='Test Lab',
            description='Test lab group'
        )
        self.lab_group.users.add(self.user)
        
        self.reagent = Reagent.objects.create(
            reagent_name='Tris Buffer',
            cas_number='77-86-1'
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
            lot_number='LOT12345',
            supplier='Sigma-Aldrich',
            concentration=1.0,
            volume=500.0,
            unit='mL',
            storage_object=self.storage,
            expiry_date=date.today() + timedelta(days=365),
            lab_group=self.lab_group
        )
        
        self.assertEqual(stored_reagent.reagent, self.reagent)
        self.assertEqual(stored_reagent.lot_number, 'LOT12345')
        self.assertEqual(stored_reagent.supplier, 'Sigma-Aldrich')
        self.assertEqual(stored_reagent.concentration, 1.0)
        self.assertEqual(stored_reagent.volume, 500.0)
        self.assertEqual(stored_reagent.unit, 'mL')
        self.assertEqual(stored_reagent.storage_object, self.storage)
        self.assertEqual(stored_reagent.lab_group, self.lab_group)
    
    def test_stored_reagent_barcode_generation(self):
        """Test automatic barcode generation"""
        stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent,
            lot_number='LOT12345',
            lab_group=self.lab_group
        )
        
        # Barcode should be generated automatically if not provided
        # (Assuming barcode generation logic exists in model save method)
        self.assertIsNotNone(stored_reagent.barcode)
    
    def test_get_current_quantity(self):
        """Test current quantity calculation with actions"""
        stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent,
            lot_number='LOT12345',
            volume=500.0,
            unit='mL',
            lab_group=self.lab_group
        )
        
        # Initial quantity should be the original volume
        self.assertEqual(stored_reagent.get_current_quantity(), 500.0)
        
        # Add some usage actions
        ReagentAction.objects.create(
            stored_reagent=stored_reagent,
            action_type='usage',
            quantity_used=50.0,
            user=self.user,
            description='Used for experiment 1'
        )
        
        ReagentAction.objects.create(
            stored_reagent=stored_reagent,
            action_type='usage',
            quantity_used=25.0,
            user=self.user,
            description='Used for experiment 2'
        )
        
        # Current quantity should be reduced
        self.assertEqual(stored_reagent.get_current_quantity(), 425.0)  # 500 - 50 - 25
        
        # Add an addition action
        ReagentAction.objects.create(
            stored_reagent=stored_reagent,
            action_type='addition',
            quantity_used=100.0,  # Actually quantity added
            user=self.user,
            description='Refilled from new bottle'
        )
        
        # Current quantity should be increased
        self.assertEqual(stored_reagent.get_current_quantity(), 525.0)  # 425 + 100
    
    def test_low_stock_checking(self):
        """Test low stock detection"""
        stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent,
            lot_number='LOT12345',
            volume=500.0,
            minimum_stock_level=100.0,
            lab_group=self.lab_group
        )
        
        # Initially should not be low stock
        self.assertFalse(stored_reagent.check_low_stock())
        
        # Use reagent to below minimum level
        ReagentAction.objects.create(
            stored_reagent=stored_reagent,
            action_type='usage',
            quantity_used=450.0,  # Leaves 50.0, below minimum of 100.0
            user=self.user
        )
        
        # Should now be low stock
        self.assertTrue(stored_reagent.check_low_stock())
    
    def test_expiration_checking(self):
        """Test expiration date monitoring"""
        # Create reagent expiring soon
        stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent,
            lot_number='LOT12345',
            expiry_date=date.today() + timedelta(days=10),  # Expires in 10 days
            lab_group=self.lab_group
        )
        
        # Should detect upcoming expiration
        self.assertTrue(stored_reagent.check_expiration())
        
        # Create reagent with distant expiration
        stored_reagent2 = StoredReagent.objects.create(
            reagent=self.reagent,
            lot_number='LOT67890',
            expiry_date=date.today() + timedelta(days=365),  # Expires in 1 year
            lab_group=self.lab_group
        )
        
        # Should not detect upcoming expiration
        self.assertFalse(stored_reagent2.check_expiration())
    
    def test_default_folder_creation(self):
        """Test default folder creation for reagents"""
        stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent,
            lot_number='LOT12345',
            lab_group=self.lab_group
        )
        
        # Create default folders
        stored_reagent.create_default_folders()
        
        # Check that folders were created
        folders = AnnotationFolder.objects.filter(stored_reagent=stored_reagent)
        folder_names = [folder.folder_name for folder in folders]
        
        expected_folders = ['Documents', 'Protocols', 'Safety Data']
        for expected_folder in expected_folders:
            self.assertIn(expected_folder, folder_names)
    
    def test_reagent_sharing_settings(self):
        """Test reagent sharing and access control"""
        stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent,
            lot_number='LOT12345',
            lab_group=self.lab_group,
            shareable_reagent=True,
            access_all=False
        )
        
        self.assertTrue(stored_reagent.shareable_reagent)
        self.assertFalse(stored_reagent.access_all)


class ReagentActionTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.lab_group = LabGroup.objects.create(
            group_name='Test Lab',
            description='Test lab group'
        )
        
        self.reagent = Reagent.objects.create(
            reagent_name='Test Reagent'
        )
        
        self.stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent,
            lot_number='LOT12345',
            volume=500.0,
            lab_group=self.lab_group
        )
        
        self.session = Session.objects.create(
            unique_id='test-session-123',
            user=self.user
        )
    
    def test_reagent_action_creation(self):
        """Test basic reagent action creation"""
        action = ReagentAction.objects.create(
            stored_reagent=self.stored_reagent,
            action_type='usage',
            quantity_used=25.0,
            user=self.user,
            description='Used in protein assay',
            session=self.session
        )
        
        self.assertEqual(action.stored_reagent, self.stored_reagent)
        self.assertEqual(action.action_type, 'usage')
        self.assertEqual(action.quantity_used, 25.0)
        self.assertEqual(action.user, self.user)
        self.assertEqual(action.description, 'Used in protein assay')
        self.assertEqual(action.session, self.session)
    
    def test_action_type_choices(self):
        """Test valid action type choices"""
        valid_types = ['usage', 'addition', 'disposal', 'transfer', 'quality_check']
        
        for action_type in valid_types:
            action = ReagentAction.objects.create(
                stored_reagent=self.stored_reagent,
                action_type=action_type,
                quantity_used=10.0,
                user=self.user
            )
            self.assertEqual(action.action_type, action_type)
    
    def test_scalable_reagent_action(self):
        """Test scalable reagent actions with scaling factors"""
        action = ReagentAction.objects.create(
            stored_reagent=self.stored_reagent,
            action_type='usage',
            quantity_used=25.0,
            scalable=True,
            scalable_factor=2.0,
            user=self.user
        )
        
        self.assertTrue(action.scalable)
        self.assertEqual(action.scalable_factor, 2.0)
        
        # Effective quantity should be quantity_used * scalable_factor
        effective_quantity = action.quantity_used * action.scalable_factor
        self.assertEqual(effective_quantity, 50.0)


class ReagentSubscriptionTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.lab_group = LabGroup.objects.create(
            group_name='Test Lab',
            description='Test lab group'
        )
        
        self.reagent = Reagent.objects.create(
            reagent_name='Test Reagent'
        )
        
        self.stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent,
            lot_number='LOT12345',
            lab_group=self.lab_group
        )
    
    def test_subscription_creation(self):
        """Test reagent subscription creation"""
        subscription = ReagentSubscription.objects.create(
            stored_reagent=self.stored_reagent,
            user=self.user,
            notification_type='low_stock'
        )
        
        self.assertEqual(subscription.stored_reagent, self.stored_reagent)
        self.assertEqual(subscription.user, self.user)
        self.assertEqual(subscription.notification_type, 'low_stock')
        self.assertTrue(subscription.active)
    
    def test_subscription_types(self):
        """Test different subscription notification types"""
        valid_types = ['low_stock', 'expiration', 'quality_check', 'all']
        
        for notification_type in valid_types:
            subscription = ReagentSubscription.objects.create(
                stored_reagent=self.stored_reagent,
                user=self.user,
                notification_type=notification_type
            )
            self.assertEqual(subscription.notification_type, notification_type)
    
    def test_subscription_unsubscribe(self):
        """Test unsubscribing from reagent notifications"""
        # Test the unsubscribe method if it exists
        subscription = ReagentSubscription.objects.create(
            stored_reagent=self.stored_reagent,
            user=self.user,
            notification_type='low_stock'
        )
        
        # Test unsubscribe functionality
        result = self.stored_reagent.unsubscribe_user(self.user)
        self.assertTrue(result)
        
        # Subscription should be deactivated or deleted
        subscription.refresh_from_db()
        self.assertFalse(subscription.active)


class ProtocolReagentTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.protocol = ProtocolModel.objects.create(
            protocol_name='Test Protocol',
            user=self.user
        )
        self.reagent = Reagent.objects.create(
            reagent_name='Protocol Reagent'
        )
    
    def test_protocol_reagent_creation(self):
        """Test linking reagents to protocols"""
        protocol_reagent = ProtocolReagent.objects.create(
            protocol=self.protocol,
            reagent=self.reagent,
            quantity_required=100.0,
            unit='mL',
            notes='Required for step 3'
        )
        
        self.assertEqual(protocol_reagent.protocol, self.protocol)
        self.assertEqual(protocol_reagent.reagent, self.reagent)
        self.assertEqual(protocol_reagent.quantity_required, 100.0)
        self.assertEqual(protocol_reagent.unit, 'mL')


class StepReagentTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.protocol = ProtocolModel.objects.create(
            protocol_name='Test Protocol',
            user=self.user
        )
        self.step = ProtocolStep.objects.create(
            protocol=self.protocol,
            step_id=1,
            step_title='Test Step'
        )
        self.reagent = Reagent.objects.create(
            reagent_name='Step Reagent'
        )
    
    def test_step_reagent_creation(self):
        """Test linking reagents to protocol steps"""
        step_reagent = StepReagent.objects.create(
            step=self.step,
            reagent=self.reagent,
            quantity_required=50.0,
            unit='µL',
            scalable=True,
            scalable_factor=1.5
        )
        
        self.assertEqual(step_reagent.step, self.step)
        self.assertEqual(step_reagent.reagent, self.reagent)
        self.assertEqual(step_reagent.quantity_required, 50.0)
        self.assertEqual(step_reagent.unit, 'µL')
        self.assertTrue(step_reagent.scalable)
        self.assertEqual(step_reagent.scalable_factor, 1.5)


class ReagentIntegrationTest(TestCase):
    """Integration tests for reagent-related models working together"""
    
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.lab_group = LabGroup.objects.create(
            group_name='Integration Test Lab',
            description='Test lab group'
        )
        self.lab_group.users.add(self.user)
        
        self.reagent = Reagent.objects.create(
            reagent_name='Integration Test Reagent',
            cas_number='123-45-6'
        )
        
        self.storage = StorageObject.objects.create(
            object_name='Test Storage',
            object_type='freezer',
            temperature=-20,
            user=self.user
        )
        
        self.protocol = ProtocolModel.objects.create(
            protocol_name='Integration Test Protocol',
            user=self.user
        )
        
        self.session = Session.objects.create(
            unique_id='integration-test-session',
            user=self.user
        )
    
    def test_complete_reagent_workflow(self):
        """Test complete workflow from reagent to usage tracking"""
        # 1. Create stored reagent
        stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent,
            lot_number='INT-LOT-001',
            supplier='Test Supplier',
            volume=1000.0,
            unit='mL',
            concentration=2.0,
            storage_object=self.storage,
            expiry_date=date.today() + timedelta(days=180),
            minimum_stock_level=200.0,
            lab_group=self.lab_group
        )
        
        # 2. Link reagent to protocol
        protocol_reagent = ProtocolReagent.objects.create(
            protocol=self.protocol,
            reagent=self.reagent,
            quantity_required=500.0,
            unit='mL'
        )
        
        # 3. Create subscription for notifications
        subscription = ReagentSubscription.objects.create(
            stored_reagent=stored_reagent,
            user=self.user,
            notification_type='low_stock'
        )
        
        # 4. Record usage action
        usage_action = ReagentAction.objects.create(
            stored_reagent=stored_reagent,
            action_type='usage',
            quantity_used=300.0,
            user=self.user,
            session=self.session,
            description='Used in integration test protocol'
        )
        
        # 5. Record quality check action
        quality_action = ReagentAction.objects.create(
            stored_reagent=stored_reagent,
            action_type='quality_check',
            quantity_used=0.0,  # No quantity used for quality check
            user=self.user,
            description='Monthly quality verification'
        )
        
        # Verify the complete workflow
        self.assertEqual(stored_reagent.get_current_quantity(), 700.0)  # 1000 - 300
        self.assertFalse(stored_reagent.check_low_stock())  # 700 > 200 (minimum)
        self.assertFalse(stored_reagent.check_expiration())  # 180 days is not soon
        
        # Verify relationships
        self.assertIn(usage_action, stored_reagent.reagent_actions.all())
        self.assertIn(quality_action, stored_reagent.reagent_actions.all())
        self.assertEqual(protocol_reagent.reagent, self.reagent)
        self.assertTrue(subscription.active)
        
        # Test low stock scenario
        low_stock_action = ReagentAction.objects.create(
            stored_reagent=stored_reagent,
            action_type='usage',
            quantity_used=550.0,  # This will bring total to 150, below minimum of 200
            user=self.user,
            description='Large usage causing low stock'
        )
        
        # Should now trigger low stock
        self.assertEqual(stored_reagent.get_current_quantity(), 150.0)  # 700 - 550
        self.assertTrue(stored_reagent.check_low_stock())  # 150 < 200