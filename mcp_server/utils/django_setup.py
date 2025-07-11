"""
Django environment setup for MCP server

This module handles Django ORM setup and authentication integration
for the MCP server to access the Cupcake database models.
"""

import os
import sys
import django
from pathlib import Path
from typing import Optional
from cc.models import ProtocolModel
from rest_framework.authtoken.models import Token

def setup_django_environment():
    """
    Initialize Django environment for MCP server access to models.
    
    This function sets up Django so that the MCP server can access
    all the Cupcake models and use the existing authentication system.
    """
    # Add the parent directory to Python path for imports
    cupcake_root = Path(__file__).parent.parent.parent
    if str(cupcake_root) not in sys.path:
        sys.path.insert(0, str(cupcake_root))
    
    # Set Django settings module
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cupcake.settings')
    
    # Setup Django
    django.setup()


def get_authenticated_user(token_key: str):
    """
    Authenticate user using Django REST Framework token.
    
    Args:
        token_key (str): Authentication token key
        
    Returns:
        User object if token is valid, None otherwise
    """
    try:

        token = Token.objects.get(key=token_key)
        return token.user
    except (Token.DoesNotExist, Exception):
        return None


def validate_user_permissions(user, protocol_id: int) -> bool:
    """
    Check if user has access to a specific protocol.
    
    Args:
        user: Django User object
        protocol_id (int): Protocol ID to check access for
        
    Returns:
        bool: True if user has access, False otherwise
    """
    if not user or not user.is_authenticated:
        return False
    
    try:
        protocol = ProtocolModel.objects.get(id=protocol_id)
        
        # Check if user is owner, editor, viewer, or protocol is enabled (public)
        if (protocol.user == user or 
            user in protocol.editors.all() or 
            user in protocol.viewers.all() or 
            protocol.enabled):
            return True
            
    except ProtocolModel.DoesNotExist:
        pass
    
    return False


def get_protocol_steps(protocol_id: int, user=None):
    """
    Get all steps for a protocol with proper permission checking.
    
    Args:
        protocol_id (int): Protocol ID
        user: Django User object for permission checking
        
    Returns:
        QuerySet of ProtocolStep objects or None if no access
    """
    if user and not validate_user_permissions(user, protocol_id):
        return None
    
    try:

        protocol = ProtocolModel.objects.get(id=protocol_id)
        return protocol.steps.all().order_by('id')
    except ProtocolModel.DoesNotExist:
        return None


def get_ontology_models():
    """
    Get all ontology model classes for term matching.
    
    Returns:
        dict: Dictionary mapping ontology names to model classes
    """
    from cc.models import (
        HumanDisease, MSUniqueVocabularies, Species, 
        SubcellularLocation, Tissue, Unimod, CellType,
        MondoDisease, UberonAnatomy, NCBITaxonomy, 
        ChEBICompound, PSIMSOntology
    )
    
    return {
        # Legacy ontologies
        'human_disease': HumanDisease,
        'ms_vocabularies': MSUniqueVocabularies,
        'species': Species,
        'subcellular_location': SubcellularLocation,
        'tissue': Tissue,
        'unimod': Unimod,
        'cell_type': CellType,
        
        # Enhanced ontologies
        'mondo_disease': MondoDisease,
        'uberon_anatomy': UberonAnatomy,
        'ncbi_taxonomy': NCBITaxonomy,
        'chebi_compound': ChEBICompound,
        'psims_ontology': PSIMSOntology
    }


# Initialize Django when this module is imported
setup_django_environment()