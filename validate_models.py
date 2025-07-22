#!/usr/bin/env python
"""
Simple model validation script to check field definitions without requiring database.
This validates that our test fixes are correct.
"""
import os
import django

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cupcake.settings')
django.setup()

from cc.models import Instrument, InstrumentJob, RemoteHost, BillingRecord

def validate_instrument_model():
    """Validate Instrument model fields"""
    print("Validating Instrument model...")
    
    # Check that instrument_type field does NOT exist
    field_names = [field.name for field in Instrument._meta.get_fields()]
    
    if 'instrument_type' in field_names:
        print("❌ ERROR: instrument_type field found in Instrument model (should not exist)")
        return False
    
    # Check that correct fields exist
    required_fields = ['instrument_name', 'instrument_description']
    for field in required_fields:
        if field not in field_names:
            print(f"❌ ERROR: {field} field missing from Instrument model")
            return False
    
    print("✅ Instrument model validation passed")
    return True

def validate_instrument_job_model():
    """Validate InstrumentJob model fields"""
    print("Validating InstrumentJob model...")
    
    field_names = [field.name for field in InstrumentJob._meta.get_fields()]
    field_dict = {field.name: field for field in InstrumentJob._meta.get_fields()}
    
    # Check injection_volume is FloatField
    if 'injection_volume' not in field_names:
        print("❌ ERROR: injection_volume field missing from InstrumentJob model")
        return False
    
    injection_volume_field = field_dict['injection_volume']
    if not hasattr(injection_volume_field, 'get_internal_type') or injection_volume_field.get_internal_type() != 'FloatField':
        print(f"❌ ERROR: injection_volume should be FloatField, got {type(injection_volume_field)}")
        return False
    
    # Check sample_number is IntegerField
    if 'sample_number' in field_names:
        sample_number_field = field_dict['sample_number']
        if not hasattr(sample_number_field, 'get_internal_type') or sample_number_field.get_internal_type() != 'IntegerField':
            print(f"❌ ERROR: sample_number should be IntegerField, got {type(sample_number_field)}")
            return False
    
    print("✅ InstrumentJob model validation passed")
    return True

def validate_remote_host_model():
    """Validate RemoteHost model fields"""
    print("Validating RemoteHost model...")
    
    field_names = [field.name for field in RemoteHost._meta.get_fields()]
    
    # Check that correct fields exist (not host_url which was used in broken tests)
    required_fields = ['host_name', 'host_port', 'host_protocol']
    for field in required_fields:
        if field not in field_names:
            print(f"❌ ERROR: {field} field missing from RemoteHost model")
            return False
    
    # Check that host_url doesn't exist (was used incorrectly in tests)
    if 'host_url' in field_names:
        print("❌ ERROR: host_url field found (tests should use host_name, host_port, host_protocol)")
        return False
    
    print("✅ RemoteHost model validation passed")
    return True

def validate_lab_group_model():
    """Validate LabGroup model fields"""
    print("Validating LabGroup model...")
    
    from cc.models import LabGroup
    field_names = [field.name for field in LabGroup._meta.get_fields()]
    
    # Check correct field names
    required_fields = ['name', 'description']  # NOT group_name, group_description
    for field in required_fields:
        if field not in field_names:
            print(f"❌ ERROR: {field} field missing from LabGroup model")
            return False
    
    # Check incorrect field names don't exist
    incorrect_fields = ['group_name', 'group_description']
    for field in incorrect_fields:
        if field in field_names:
            print(f"❌ ERROR: {field} field found (should be {field.replace('group_', '')})")
            return False
    
    print("✅ LabGroup model validation passed")
    return True

def validate_billing_record_model():
    """Validate BillingRecord model fields"""
    print("Validating BillingRecord model...")
    
    try:
        field_names = [field.name for field in BillingRecord._meta.get_fields()]
        print(f"BillingRecord fields: {field_names}")
        
        # Just check that the model can be imported and has basic fields
        if 'user' not in field_names:
            print("❌ ERROR: user field missing from BillingRecord model")
            return False
            
        print("✅ BillingRecord model validation passed")
        return True
    except Exception as e:
        print(f"❌ ERROR: Could not validate BillingRecord model: {e}")
        return False

def main():
    print("=== Model Field Validation ===")
    
    results = []
    results.append(validate_instrument_model())
    results.append(validate_instrument_job_model())
    results.append(validate_remote_host_model())
    results.append(validate_lab_group_model())
    results.append(validate_billing_record_model())
    
    if all(results):
        print("\n🎉 All model validations passed! Test field fixes are correct.")
        exit(0)
    else:
        print("\n❌ Some model validations failed. Check the errors above.")
        exit(1)

if __name__ == "__main__":
    main()