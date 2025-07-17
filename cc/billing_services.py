"""
Billing Services Module

This module provides comprehensive billing and pricing functionality including:
- Public pricing display and quote generation
- Service tier and price management
- Billing record operations
- Quote calculations and estimations
"""

from decimal import Decimal
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union, Any
from django.db.models import QuerySet, Q
from django.utils import timezone
from django.contrib.auth.models import User

from .models import (
    ServiceTier, ServicePrice, BillingRecord, Instrument, 
    InstrumentJob, LabGroup
)


class BillingService:
    """Main billing service class for handling all billing operations"""
    
    def __init__(self, lab_group: Optional[LabGroup] = None):
        self.lab_group = lab_group
    
    def get_active_service_tiers(self) -> QuerySet:
        """Get all active service tiers"""
        queryset = ServiceTier.objects.filter(is_active=True)
        if self.lab_group:
            queryset = queryset.filter(lab_group=self.lab_group)
        return queryset.order_by('name')
    
    def get_active_pricing(self, instrument: Optional[Instrument] = None) -> QuerySet:
        """Get active pricing for instruments"""
        queryset = ServicePrice.objects.filter(
            is_active=True,
            service_tier__is_active=True,
            effective_date__lte=timezone.now().date()
        ).filter(
            Q(expiry_date__isnull=True) | Q(expiry_date__gte=timezone.now().date())
        )
        
        if instrument:
            queryset = queryset.filter(instrument=instrument)
        
        if self.lab_group:
            queryset = queryset.filter(service_tier__lab_group=self.lab_group)
        
        return queryset.select_related('service_tier', 'instrument').order_by(
            'service_tier__name', 'instrument__instrument_name', 'billing_unit'
        )
    
    def get_pricing_by_tier(self, service_tier: ServiceTier) -> QuerySet:
        """Get all pricing for a specific service tier"""
        return self.get_active_pricing().filter(service_tier=service_tier)
    
    def get_pricing_by_instrument(self, instrument: Instrument) -> QuerySet:
        """Get all pricing for a specific instrument"""
        return self.get_active_pricing().filter(instrument=instrument)


class QuoteCalculator:
    """Service for calculating quotes and estimates"""
    
    def __init__(self, service_tier: ServiceTier):
        self.service_tier = service_tier
        self.billing_service = BillingService(service_tier.lab_group)
    
    def calculate_quote(self, quote_request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate a quote based on the request parameters
        
        Args:
            quote_request: Dictionary containing:
                - instrument_id: ID of the instrument
                - samples: Number of samples
                - injections_per_sample: Number of injections per sample
                - estimated_instrument_hours: Estimated instrument time
                - estimated_personnel_hours: Estimated personnel time
                - additional_services: List of additional services
        
        Returns:
            Dictionary with quote details and total cost
        """
        try:
            instrument = Instrument.objects.get(id=quote_request['instrument_id'])
            pricing = self.billing_service.get_pricing_by_instrument(instrument).filter(
                service_tier=self.service_tier
            )
            
            quote_details = {
                'instrument': {
                    'id': instrument.id,
                    'name': instrument.instrument_name,
                    'description': instrument.instrument_description
                },
                'service_tier': {
                    'id': self.service_tier.id,
                    'name': self.service_tier.name,
                    'description': self.service_tier.description
                },
                'line_items': [],
                'subtotal': Decimal('0.00'),
                'total': Decimal('0.00'),
                'currency': 'USD',
                'valid_until': (timezone.now() + timedelta(days=30)).date(),
                'generated_at': timezone.now()
            }
            
            # Calculate sample-based pricing
            samples = quote_request.get('samples', 0)
            if samples > 0:
                sample_pricing = pricing.filter(billing_unit='per_sample').first()
                if sample_pricing:
                    cost = sample_pricing.price * samples
                    quote_details['line_items'].append({
                        'type': 'per_sample',
                        'description': f'Sample Analysis ({samples} samples)',
                        'quantity': samples,
                        'unit_price': sample_pricing.price,
                        'total_price': cost,
                        'billing_unit': 'per_sample'
                    })
                    quote_details['subtotal'] += cost
            
            # Calculate injection-based pricing
            injections = quote_request.get('injections_per_sample', 0) * samples
            if injections > 0:
                injection_pricing = pricing.filter(billing_unit='per_injection').first()
                if injection_pricing:
                    cost = injection_pricing.price * injections
                    quote_details['line_items'].append({
                        'type': 'per_injection',
                        'description': f'Injections ({injections} injections)',
                        'quantity': injections,
                        'unit_price': injection_pricing.price,
                        'total_price': cost,
                        'billing_unit': 'per_injection'
                    })
                    quote_details['subtotal'] += cost
            
            # Calculate instrument time pricing
            instrument_hours = quote_request.get('estimated_instrument_hours', 0)
            if instrument_hours > 0:
                instrument_pricing = pricing.filter(billing_unit='per_hour_instrument').first()
                if instrument_pricing:
                    cost = instrument_pricing.price * Decimal(str(instrument_hours))
                    quote_details['line_items'].append({
                        'type': 'per_hour_instrument',
                        'description': f'Instrument Time ({instrument_hours} hours)',
                        'quantity': instrument_hours,
                        'unit_price': instrument_pricing.price,
                        'total_price': cost,
                        'billing_unit': 'per_hour_instrument'
                    })
                    quote_details['subtotal'] += cost
            
            # Calculate personnel time pricing
            personnel_hours = quote_request.get('estimated_personnel_hours', 0)
            if personnel_hours > 0:
                personnel_pricing = pricing.filter(billing_unit='per_hour_personnel').first()
                if personnel_pricing:
                    cost = personnel_pricing.price * Decimal(str(personnel_hours))
                    quote_details['line_items'].append({
                        'type': 'per_hour_personnel',
                        'description': f'Personnel Time ({personnel_hours} hours)',
                        'quantity': personnel_hours,
                        'unit_price': personnel_pricing.price,
                        'total_price': cost,
                        'billing_unit': 'per_hour_personnel'
                    })
                    quote_details['subtotal'] += cost
            
            # Add flat rate services
            flat_rate_pricing = pricing.filter(billing_unit='flat_rate')
            for flat_rate in flat_rate_pricing:
                if quote_request.get(f'include_flat_rate_{flat_rate.id}', False):
                    quote_details['line_items'].append({
                        'type': 'flat_rate',
                        'description': f'Flat Rate Service',
                        'quantity': 1,
                        'unit_price': flat_rate.price,
                        'total_price': flat_rate.price,
                        'billing_unit': 'flat_rate'
                    })
                    quote_details['subtotal'] += flat_rate.price
            
            quote_details['total'] = quote_details['subtotal']
            
            return {
                'success': True,
                'quote': quote_details
            }
            
        except Instrument.DoesNotExist:
            return {
                'success': False,
                'error': 'Instrument not found'
            }
        except Exception as e:
            return {
                'success': False,
                'error': f'Quote calculation failed: {str(e)}'
            }
    
    def get_pricing_options(self, instrument: Instrument) -> Dict[str, Any]:
        """Get all pricing options for an instrument under this service tier"""
        pricing = self.billing_service.get_pricing_by_instrument(instrument).filter(
            service_tier=self.service_tier
        )
        
        options = {
            'instrument': {
                'id': instrument.id,
                'name': instrument.instrument_name,
                'description': instrument.instrument_description
            },
            'service_tier': {
                'id': self.service_tier.id,
                'name': self.service_tier.name,
                'description': self.service_tier.description
            },
            'pricing_options': []
        }
        
        for price in pricing:
            options['pricing_options'].append({
                'id': price.id,
                'billing_unit': price.billing_unit,
                'billing_unit_display': price.get_billing_unit_display(),
                'price': price.price,
                'currency': price.currency,
                'effective_date': price.effective_date,
                'expiry_date': price.expiry_date
            })
        
        return options


class PricingManager:
    """Service for managing pricing and service tiers"""
    
    def __init__(self, lab_group: LabGroup):
        self.lab_group = lab_group
    
    def create_service_tier(self, name: str, description: str = "") -> ServiceTier:
        """Create a new service tier"""
        return ServiceTier.objects.create(
            name=name,
            description=description,
            lab_group=self.lab_group
        )
    
    def update_service_tier(self, tier_id: int, **kwargs) -> ServiceTier:
        """Update an existing service tier"""
        tier = ServiceTier.objects.get(id=tier_id, lab_group=self.lab_group)
        for key, value in kwargs.items():
            setattr(tier, key, value)
        tier.save()
        return tier
    
    def create_service_price(self, service_tier: ServiceTier, instrument: Instrument, 
                           price: Decimal, billing_unit: str, **kwargs) -> ServicePrice:
        """Create a new service price"""
        return ServicePrice.objects.create(
            service_tier=service_tier,
            instrument=instrument,
            price=price,
            billing_unit=billing_unit,
            **kwargs
        )
    
    def update_service_price(self, price_id: int, **kwargs) -> ServicePrice:
        """Update an existing service price"""
        price = ServicePrice.objects.get(
            id=price_id,
            service_tier__lab_group=self.lab_group
        )
        for key, value in kwargs.items():
            setattr(price, key, value)
        price.save()
        return price
    
    def bulk_update_prices(self, price_updates: List[Dict[str, Any]]) -> List[ServicePrice]:
        """Bulk update multiple prices"""
        updated_prices = []
        for update in price_updates:
            price_id = update.pop('id')
            price = self.update_service_price(price_id, **update)
            updated_prices.append(price)
        return updated_prices
    
    def get_pricing_summary(self) -> Dict[str, Any]:
        """Get a summary of all pricing for this lab group"""
        service_tiers = self.lab_group.service_tiers.filter(is_active=True)
        instruments = Instrument.objects.filter(enabled=True)
        
        summary = {
            'lab_group': {
                'id': self.lab_group.id,
                'name': self.lab_group.name,
                'description': self.lab_group.description
            },
            'service_tiers': [],
            'instruments': [],
            'total_pricing_entries': 0
        }
        
        for tier in service_tiers:
            tier_data = {
                'id': tier.id,
                'name': tier.name,
                'description': tier.description,
                'pricing_count': tier.prices.filter(is_active=True).count()
            }
            summary['service_tiers'].append(tier_data)
            summary['total_pricing_entries'] += tier_data['pricing_count']
        
        for instrument in instruments:
            instrument_data = {
                'id': instrument.id,
                'name': instrument.instrument_name,
                'description': instrument.instrument_description,
                'pricing_count': ServicePrice.objects.filter(
                    instrument=instrument,
                    service_tier__lab_group=self.lab_group,
                    is_active=True
                ).count()
            }
            summary['instruments'].append(instrument_data)
        
        return summary


class BillingRecordManager:
    """Service for managing billing records"""
    
    def __init__(self, lab_group: Optional[LabGroup] = None):
        self.lab_group = lab_group
    
    def create_billing_record(self, instrument_job: InstrumentJob, 
                            service_tier: ServiceTier, **kwargs) -> BillingRecord:
        """Create a new billing record"""
        return BillingRecord.objects.create(
            user=instrument_job.user,
            instrument_job=instrument_job,
            service_tier=service_tier,
            **kwargs
        )
    
    def get_billing_records(self, user: Optional[User] = None, 
                          status: Optional[str] = None) -> QuerySet:
        """Get billing records with optional filtering"""
        queryset = BillingRecord.objects.all()
        
        if self.lab_group:
            queryset = queryset.filter(service_tier__lab_group=self.lab_group)
        
        if user:
            queryset = queryset.filter(user=user)
        
        if status:
            queryset = queryset.filter(status=status)
        
        return queryset.select_related('user', 'instrument_job', 'service_tier')
    
    def generate_invoice_number(self) -> str:
        """Generate a unique invoice number"""
        import uuid
        timestamp = timezone.now().strftime('%Y%m%d')
        short_uuid = str(uuid.uuid4())[:8].upper()
        return f"INV-{timestamp}-{short_uuid}"
    
    def mark_as_billed(self, billing_record_id: int) -> BillingRecord:
        """Mark a billing record as billed"""
        record = BillingRecord.objects.get(id=billing_record_id)
        record.status = 'billed'
        if not record.invoice_number:
            record.invoice_number = self.generate_invoice_number()
        record.save()
        return record
    
    def mark_as_paid(self, billing_record_id: int) -> BillingRecord:
        """Mark a billing record as paid"""
        record = BillingRecord.objects.get(id=billing_record_id)
        record.status = 'paid'
        record.paid_date = timezone.now().date()
        record.save()
        return record


class PublicPricingService:
    """Service for displaying public pricing information"""
    
    def __init__(self, lab_group: Optional[LabGroup] = None):
        self.lab_group = lab_group
        self.billing_service = BillingService(lab_group)
    
    def get_public_pricing_display(self) -> Dict[str, Any]:
        """Get pricing information formatted for public display"""
        service_tiers = self.billing_service.get_active_service_tiers()
        
        pricing_display = {
            'lab_group': {
                'id': self.lab_group.id if self.lab_group else None,
                'name': self.lab_group.name if self.lab_group else 'All Services',
                'description': self.lab_group.description if self.lab_group else ''
            },
            'service_tiers': [],
            'instruments': [],
            'last_updated': timezone.now()
        }
        
        # Get all instruments with active pricing
        instruments_with_pricing = set()
        all_pricing = self.billing_service.get_active_pricing()
        
        for tier in service_tiers:
            tier_pricing = all_pricing.filter(service_tier=tier)
            
            tier_data = {
                'id': tier.id,
                'name': tier.name,
                'description': tier.description,
                'instruments': []
            }
            
            # Group pricing by instrument
            tier_instruments = {}
            for price in tier_pricing:
                instrument = price.instrument
                instruments_with_pricing.add(instrument)
                
                if instrument.id not in tier_instruments:
                    tier_instruments[instrument.id] = {
                        'id': instrument.id,
                        'name': instrument.instrument_name,
                        'description': instrument.instrument_description,
                        'pricing': []
                    }
                
                tier_instruments[instrument.id]['pricing'].append({
                    'billing_unit': price.billing_unit,
                    'billing_unit_display': price.get_billing_unit_display(),
                    'price': price.price,
                    'currency': price.currency
                })
            
            tier_data['instruments'] = list(tier_instruments.values())
            pricing_display['service_tiers'].append(tier_data)
        
        # Add instruments summary
        for instrument in instruments_with_pricing:
            instrument_pricing = all_pricing.filter(instrument=instrument)
            
            price_range = {
                'min_price': min(p.price for p in instrument_pricing),
                'max_price': max(p.price for p in instrument_pricing),
                'currency': 'USD'
            }
            
            pricing_display['instruments'].append({
                'id': instrument.id,
                'name': instrument.instrument_name,
                'description': instrument.instrument_description,
                'price_range': price_range,
                'available_tiers': len(set(p.service_tier.id for p in instrument_pricing))
            })
        
        return pricing_display
    
    def generate_quote_form_config(self) -> Dict[str, Any]:
        """Generate configuration for quote request form"""
        instruments = Instrument.objects.filter(enabled=True)
        service_tiers = self.billing_service.get_active_service_tiers()
        
        form_config = {
            'instruments': [
                {
                    'id': inst.id,
                    'name': inst.instrument_name,
                    'description': inst.instrument_description
                }
                for inst in instruments
            ],
            'service_tiers': [
                {
                    'id': tier.id,
                    'name': tier.name,
                    'description': tier.description
                }
                for tier in service_tiers
            ],
            'billing_units': [
                {'value': choice[0], 'display': choice[1]}
                for choice in ServicePrice.BILLING_UNIT_CHOICES
            ],
            'form_fields': {
                'required': ['instrument_id', 'service_tier_id', 'samples'],
                'optional': [
                    'injections_per_sample', 'estimated_instrument_hours',
                    'estimated_personnel_hours', 'contact_email', 'notes'
                ]
            }
        }
        
        return form_config