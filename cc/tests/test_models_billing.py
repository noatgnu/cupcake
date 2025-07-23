"""
Tests for billing system models: ServiceTier, ServicePrice, BillingRecord
"""
from decimal import Decimal
from datetime import date, timedelta
from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from cc.models import (
    ServiceTier, ServicePrice, BillingRecord, LabGroup, Instrument, InstrumentJob,
    MetadataColumn, Project
)


class ServiceTierModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.lab_group = LabGroup.objects.create(
            name='Test Lab Group',
            description='Test group for billing'
        )
        self.lab_group.managers.add(self.user)
    
    def test_service_tier_creation(self):
        """Test basic service tier creation"""
        tier = ServiceTier.objects.create(
            name='Academic',
            description='Academic pricing tier',
            lab_group=self.lab_group
        )
        self.assertEqual(tier.name, 'Academic')
        self.assertEqual(tier.description, 'Academic pricing tier')
        self.assertEqual(tier.lab_group, self.lab_group)
        self.assertTrue(tier.is_active)
        self.assertIsNotNone(tier.created_at)
        self.assertIsNotNone(tier.updated_at)
    
    def test_service_tier_str_representation(self):
        """Test service tier string representation"""
        tier = ServiceTier.objects.create(
            name='Commercial',
            lab_group=self.lab_group
        )
        expected_str = f"{self.lab_group.name} - Commercial"
        self.assertEqual(str(tier), expected_str)
    
    def test_service_tier_unique_constraint(self):
        """Test that service tier names must be unique within a lab group"""
        ServiceTier.objects.create(
            name='Academic',
            lab_group=self.lab_group
        )
        
        with self.assertRaises(IntegrityError):
            ServiceTier.objects.create(
                name='Academic',  # Same name
                lab_group=self.lab_group  # Same lab group
            )
    
    def test_service_tier_different_lab_groups(self):
        """Test that same tier names can exist in different lab groups"""
        other_lab_group = LabGroup.objects.create(
            name='Other Lab Group'
        )
        other_lab_group.managers.add(self.user)
        
        tier1 = ServiceTier.objects.create(
            name='Academic',
            lab_group=self.lab_group
        )
        
        tier2 = ServiceTier.objects.create(
            name='Academic',  # Same name, different lab group
            lab_group=other_lab_group
        )
        
        self.assertEqual(tier1.name, tier2.name)
        self.assertNotEqual(tier1.lab_group, tier2.lab_group)
    
    def test_service_tier_ordering(self):
        """Test service tier ordering"""
        tier_z = ServiceTier.objects.create(name='Z Tier', lab_group=self.lab_group)
        tier_a = ServiceTier.objects.create(name='A Tier', lab_group=self.lab_group)
        tier_m = ServiceTier.objects.create(name='M Tier', lab_group=self.lab_group)
        
        tiers = list(ServiceTier.objects.all())
        self.assertEqual(tiers[0], tier_a)
        self.assertEqual(tiers[1], tier_m)
        self.assertEqual(tiers[2], tier_z)


class ServicePriceModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.lab_group = LabGroup.objects.create(
            name='Test Lab Group'
        )
        self.lab_group.managers.add(self.user)
        self.service_tier = ServiceTier.objects.create(
            name='Academic',
            lab_group=self.lab_group
        )
        self.instrument = Instrument.objects.create(
            instrument_name='Test Instrument',
            instrument_description='Test instrument for billing'
        )
    
    def test_service_price_creation(self):
        """Test basic service price creation"""
        price = ServicePrice.objects.create(
            service_tier=self.service_tier,
            instrument=self.instrument,
            price=Decimal('50.00'),
            billing_unit='per_hour_instrument',
            currency='USD'
        )
        
        self.assertEqual(price.service_tier, self.service_tier)
        self.assertEqual(price.instrument, self.instrument)
        self.assertEqual(price.price, Decimal('50.00'))
        self.assertEqual(price.billing_unit, 'per_hour_instrument')
        self.assertEqual(price.currency, 'USD')
        self.assertTrue(price.is_active)
        self.assertIsNotNone(price.effective_date)
        self.assertIsNone(price.expiry_date)
    
    def test_service_price_str_representation(self):
        """Test service price string representation"""
        price = ServicePrice.objects.create(
            service_tier=self.service_tier,
            instrument=self.instrument,
            price=Decimal('25.50'),
            billing_unit='per_sample'
        )
        
        expected_str = f"{self.service_tier.name} - {self.instrument.instrument_name} - Per Sample: 25.50"
        self.assertEqual(str(price), expected_str)
    
    def test_service_price_unique_constraint(self):
        """Test service price unique constraint"""
        ServicePrice.objects.create(
            service_tier=self.service_tier,
            instrument=self.instrument,
            price=Decimal('50.00'),
            billing_unit='per_hour_instrument'
        )
        
        with self.assertRaises(IntegrityError):
            ServicePrice.objects.create(
                service_tier=self.service_tier,  # Same tier
                instrument=self.instrument,     # Same instrument
                price=Decimal('60.00'),         # Different price
                billing_unit='per_hour_instrument'  # Same billing unit
            )
    
    def test_service_price_billing_unit_choices(self):
        """Test all billing unit choices"""
        billing_units = [
            'per_sample',
            'per_hour_instrument',
            'per_hour_personnel',
            'per_injection',
            'flat_rate'
        ]
        
        for unit in billing_units:
            price = ServicePrice.objects.create(
                service_tier=self.service_tier,
                instrument=self.instrument,
                price=Decimal('100.00'),
                billing_unit=unit
            )
            self.assertEqual(price.billing_unit, unit)
    
    def test_service_price_expiry_functionality(self):
        """Test service price expiry date functionality"""
        future_date = date.today() + timedelta(days=30)
        past_date = date.today() - timedelta(days=30)
        
        # Active price (no expiry)
        active_price = ServicePrice.objects.create(
            service_tier=self.service_tier,
            instrument=self.instrument,
            price=Decimal('50.00'),
            billing_unit='per_sample'
        )
        
        # Future expiry price
        future_expiry_price = ServicePrice.objects.create(
            service_tier=self.service_tier,
            instrument=self.instrument,
            price=Decimal('60.00'),
            billing_unit='per_hour_instrument',
            expiry_date=future_date
        )
        
        # Expired price
        expired_price = ServicePrice.objects.create(
            service_tier=self.service_tier,
            instrument=self.instrument,
            price=Decimal('40.00'),
            billing_unit='per_hour_personnel',
            expiry_date=past_date
        )
        
        self.assertIsNone(active_price.expiry_date)
        self.assertEqual(future_expiry_price.expiry_date, future_date)
        self.assertEqual(expired_price.expiry_date, past_date)


class BillingRecordModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.project = Project.objects.create(project_name='Test Project')
        self.lab_group = LabGroup.objects.create(
            name='Test Lab Group'
        )
        self.lab_group.managers.add(self.user)
        self.service_tier = ServiceTier.objects.create(
            name='Academic',
            lab_group=self.lab_group
        )
        self.instrument = Instrument.objects.create(
            instrument_name='Test Instrument'
        )
        
        # Create metadata column for instrument job
        self.metadata_column = MetadataColumn.objects.create(
            name='Test Column',
            value='Test Value'
        )
        
        # Create instrument job
        self.instrument_job = InstrumentJob.objects.create(
            user=self.user,
            instrument=self.instrument,
            project=self.project,
            sample_number=10,
            service_lab_group=self.lab_group,
            cost_center='CC001',
            amount=Decimal('1000.00')
        )
        self.instrument_job.user_metadata.add(self.metadata_column)
    
    def test_billing_record_creation(self):
        """Test basic billing record creation"""
        billing = BillingRecord.objects.create(
            user=self.user,
            instrument_job=self.instrument_job,
            service_tier=self.service_tier,
            instrument_hours=Decimal('2.5'),
            instrument_rate=Decimal('50.00'),
            instrument_cost=Decimal('125.00'),
            personnel_hours=Decimal('1.0'),
            personnel_rate=Decimal('30.00'),
            personnel_cost=Decimal('30.00'),
            other_quantity=Decimal('10'),
            other_rate=Decimal('5.00'),
            other_cost=Decimal('50.00'),
            other_description='Sample processing',
            total_amount=Decimal('205.00')
        )
        
        self.assertEqual(billing.user, self.user)
        self.assertEqual(billing.instrument_job, self.instrument_job)
        self.assertEqual(billing.service_tier, self.service_tier)
        self.assertEqual(billing.instrument_hours, Decimal('2.5'))
        self.assertEqual(billing.instrument_cost, Decimal('125.00'))
        self.assertEqual(billing.personnel_cost, Decimal('30.00'))
        self.assertEqual(billing.other_cost, Decimal('50.00'))
        self.assertEqual(billing.total_amount, Decimal('205.00'))
        self.assertEqual(billing.status, 'pending')
    
    def test_billing_record_auto_total_calculation(self):
        """Test automatic total calculation on save"""
        billing = BillingRecord.objects.create(
            user=self.user,
            instrument_job=self.instrument_job,
            service_tier=self.service_tier,
            instrument_cost=Decimal('100.00'),
            personnel_cost=Decimal('50.00'),
            other_cost=Decimal('25.00'),
            total_amount=Decimal('0.00')  # Will be overridden
        )
        
        # Total should be calculated automatically
        self.assertEqual(billing.total_amount, Decimal('175.00'))
    
    def test_billing_record_auto_total_with_nulls(self):
        """Test automatic total calculation with null values"""
        billing = BillingRecord.objects.create(
            user=self.user,
            instrument_job=self.instrument_job,
            service_tier=self.service_tier,
            instrument_cost=Decimal('100.00'),
            # personnel_cost and other_cost are None
            total_amount=Decimal('0.00')
        )
        
        # Total should only include non-null values
        self.assertEqual(billing.total_amount, Decimal('100.00'))
    
    def test_billing_record_str_representation(self):
        """Test billing record string representation"""
        billing = BillingRecord.objects.create(
            user=self.user,
            instrument_job=self.instrument_job,
            service_tier=self.service_tier,
            total_amount=Decimal('150.00')
        )
        
        expected_str = f"Billing for {self.user.username} - {self.instrument.instrument_name} - 150.00"
        self.assertEqual(str(billing), expected_str)
    
    def test_billing_record_status_choices(self):
        """Test all billing record status choices"""
        statuses = ['pending', 'billed', 'paid', 'cancelled']
        
        for status in statuses:
            billing = BillingRecord.objects.create(
                user=self.user,
                instrument_job=self.instrument_job,
                service_tier=self.service_tier,
                status=status,
                total_amount=Decimal('100.00')
            )
            self.assertEqual(billing.status, status)
    
    def test_billing_record_ordering(self):
        """Test billing record ordering by billing date"""
        from django.utils import timezone
        import datetime
        
        # Create billing records on different dates
        old_billing = BillingRecord.objects.create(
            user=self.user,
            instrument_job=self.instrument_job,
            service_tier=self.service_tier,
            total_amount=Decimal('100.00')
        )
        
        # Manually set earlier date
        old_billing.billing_date = date.today() - timedelta(days=5)
        old_billing.save()
        
        new_billing = BillingRecord.objects.create(
            user=self.user,
            instrument_job=self.instrument_job,
            service_tier=self.service_tier,
            total_amount=Decimal('200.00')
        )
        
        billings = list(BillingRecord.objects.all())
        self.assertEqual(billings[0], new_billing)  # Newest first
        self.assertEqual(billings[1], old_billing)
    
    def test_billing_record_complex_calculation(self):
        """Test complex billing calculation scenario"""
        billing = BillingRecord.objects.create(
            user=self.user,
            instrument_job=self.instrument_job,
            service_tier=self.service_tier,
            instrument_hours=Decimal('4.25'),
            instrument_rate=Decimal('75.50'),
            personnel_hours=Decimal('2.75'),
            personnel_rate=Decimal('45.00'),
            other_quantity=Decimal('15'),
            other_rate=Decimal('12.50'),
            other_description='Special reagents',
            total_amount=Decimal('0.00')  # Will be calculated
        )
        
        # Calculate expected costs
        expected_instrument = Decimal('4.25') * Decimal('75.50')  # 320.875 -> 320.88
        expected_personnel = Decimal('2.75') * Decimal('45.00')   # 123.75
        expected_other = Decimal('15') * Decimal('12.50')         # 187.50
        
        # Refresh from database to get calculated values
        billing.refresh_from_db()
        
        self.assertEqual(billing.instrument_cost, expected_instrument)
        self.assertEqual(billing.personnel_cost, expected_personnel)
        self.assertEqual(billing.other_cost, expected_other)
        
        expected_total = expected_instrument + expected_personnel + expected_other
        self.assertEqual(billing.total_amount, expected_total)


class BillingIntegrationTest(TestCase):
    """Integration tests for the billing system"""
    
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.project = Project.objects.create(project_name='Test Project')
        self.lab_group = LabGroup.objects.create(
            name='Proteomics Core'
        )
        self.lab_group.managers.add(self.user)
        
        # Create service tiers
        self.academic_tier = ServiceTier.objects.create(
            name='Academic',
            description='Academic pricing',
            lab_group=self.lab_group
        )
        
        self.commercial_tier = ServiceTier.objects.create(
            name='Commercial',
            description='Commercial pricing',
            lab_group=self.lab_group
        )
        
        # Create instrument
        self.instrument = Instrument.objects.create(
            instrument_name='LC-MS/MS System'
        )
        
        # Create prices
        self.academic_price = ServicePrice.objects.create(
            service_tier=self.academic_tier,
            instrument=self.instrument,
            price=Decimal('50.00'),
            billing_unit='per_hour_instrument'
        )
        
        self.commercial_price = ServicePrice.objects.create(
            service_tier=self.commercial_tier,
            instrument=self.instrument,
            price=Decimal('125.00'),
            billing_unit='per_hour_instrument'
        )
        
        # Create instrument job
        self.instrument_job = InstrumentJob.objects.create(
            user=self.user,
            instrument=self.instrument,
            project=self.project,
            sample_number=5,
            service_lab_group=self.lab_group,
            cost_center='PROT001',
            amount=Decimal('500.00')
        )
    
    def test_complete_billing_workflow(self):
        """Test complete billing workflow from pricing to final billing"""
        
        # Create billing record for academic user
        academic_billing = BillingRecord.objects.create(
            user=self.user,
            instrument_job=self.instrument_job,
            service_tier=self.academic_tier,
            instrument_hours=Decimal('3.0'),
            instrument_rate=self.academic_price.price,
            instrument_cost=Decimal('3.0') * self.academic_price.price,
            total_amount=Decimal('0.00')  # Auto-calculated
        )
        
        # Verify academic billing
        self.assertEqual(academic_billing.total_amount, Decimal('150.00'))
        self.assertEqual(academic_billing.status, 'pending')
        
        # Create billing for commercial user (same usage, different rate)
        commercial_user = User.objects.create_user('commercial', 'comm@example.com', 'pass')
        commercial_job = InstrumentJob.objects.create(
            user=commercial_user,
            instrument=self.instrument,
            project=self.project,
            sample_number=5,
            service_lab_group=self.lab_group,
            cost_center='COMM001',
            amount=Decimal('1000.00')
        )
        
        commercial_billing = BillingRecord.objects.create(
            user=commercial_user,
            instrument_job=commercial_job,
            service_tier=self.commercial_tier,
            instrument_hours=Decimal('3.0'),
            instrument_rate=self.commercial_price.price,
            instrument_cost=Decimal('3.0') * self.commercial_price.price,
            total_amount=Decimal('0.00')  # Auto-calculated
        )
        
        # Verify commercial billing is higher
        self.assertEqual(commercial_billing.total_amount, Decimal('375.00'))
        self.assertGreater(commercial_billing.total_amount, academic_billing.total_amount)
        
        # Test billing progression
        academic_billing.status = 'billed'
        academic_billing.invoice_number = 'INV-2025-001'
        academic_billing.save()
        
        self.assertEqual(academic_billing.status, 'billed')
        self.assertEqual(academic_billing.invoice_number, 'INV-2025-001')
        
        # Mark as paid
        academic_billing.status = 'paid'
        academic_billing.paid_date = date.today()
        academic_billing.save()
        
        self.assertEqual(academic_billing.status, 'paid')
        self.assertEqual(academic_billing.paid_date, date.today())
    
    def test_multiple_pricing_tiers_same_instrument(self):
        """Test multiple pricing tiers for the same instrument"""
        
        # Add personnel pricing
        academic_personnel = ServicePrice.objects.create(
            service_tier=self.academic_tier,
            instrument=self.instrument,
            price=Decimal('25.00'),
            billing_unit='per_hour_personnel'
        )
        
        commercial_personnel = ServicePrice.objects.create(
            service_tier=self.commercial_tier,
            instrument=self.instrument,
            price=Decimal('75.00'),
            billing_unit='per_hour_personnel'
        )
        
        # Add sample pricing
        academic_sample = ServicePrice.objects.create(
            service_tier=self.academic_tier,
            instrument=self.instrument,
            price=Decimal('15.00'),
            billing_unit='per_sample'
        )
        
        commercial_sample = ServicePrice.objects.create(
            service_tier=self.commercial_tier,
            instrument=self.instrument,
            price=Decimal('35.00'),
            billing_unit='per_sample'
        )
        
        # Verify all prices exist
        academic_prices = ServicePrice.objects.filter(service_tier=self.academic_tier)
        commercial_prices = ServicePrice.objects.filter(service_tier=self.commercial_tier)
        
        self.assertEqual(academic_prices.count(), 3)  # instrument, personnel, sample
        self.assertEqual(commercial_prices.count(), 3)
        
        # Verify pricing differences
        academic_total_cost = (
            academic_prices.get(billing_unit='per_hour_instrument').price +
            academic_prices.get(billing_unit='per_hour_personnel').price +
            academic_prices.get(billing_unit='per_sample').price
        )
        
        commercial_total_cost = (
            commercial_prices.get(billing_unit='per_hour_instrument').price +
            commercial_prices.get(billing_unit='per_hour_personnel').price +
            commercial_prices.get(billing_unit='per_sample').price
        )
        
        self.assertLess(academic_total_cost, commercial_total_cost)