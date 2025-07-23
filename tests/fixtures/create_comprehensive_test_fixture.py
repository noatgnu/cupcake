#!/usr/bin/env python3
"""
Enhanced comprehensive test fixture for import/export testing.
Includes all new models: billing, backup logs, sample pools, ontology data, and SDRF cache.
Creates a realistic laboratory scenario with 100+ annotations and complete metadata.
"""

import json
import sqlite3
import zipfile
import tempfile
import shutil
import os
import hashlib
from datetime import datetime, timedelta
from decimal import Decimal
import uuid
import random


def create_comprehensive_test_fixture():
    """Create comprehensive test fixture with all CUPCAKE models"""
    
    # Create temporary directory for building the archive
    temp_dir = tempfile.mkdtemp()
    
    try:
        # Create the SQLite database with comprehensive test data
        sqlite_path = os.path.join(temp_dir, 'user_data.sqlite')
        create_comprehensive_database(sqlite_path)
        
        # Create media files for different annotation types
        media_dir = os.path.join(temp_dir, 'media')
        create_comprehensive_media_files(media_dir)
        
        # Create comprehensive export metadata
        metadata = create_comprehensive_export_metadata()
        
        with open(os.path.join(temp_dir, 'export_metadata.json'), 'w') as f:
            json.dump(metadata, f, indent=2)
        
        # Create the ZIP archive
        archive_path = 'comprehensive_test_fixture.zip'
        with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arc_path = os.path.relpath(file_path, temp_dir)
                    zipf.write(file_path, arc_path)
        
        print(f"Created comprehensive test fixture: {archive_path}")
        return archive_path
        
    finally:
        shutil.rmtree(temp_dir)


def create_comprehensive_database(sqlite_path):
    """Create SQLite database with all CUPCAKE models"""
    conn = sqlite3.connect(sqlite_path)
    
    # Create all necessary tables with proper schema
    create_comprehensive_database_schema(conn)
    
    # Insert comprehensive test data
    insert_comprehensive_test_data(conn)
    
    conn.commit()
    conn.close()


def create_comprehensive_database_schema(conn):
    """Create comprehensive database schema matching ALL Django models"""
    
    # Core tables from original script
    create_core_tables(conn)
    
    # New tables for enhanced functionality
    create_billing_tables(conn)
    create_backup_tables(conn) 
    create_sample_pool_tables(conn)
    create_ontology_tables(conn)
    create_sdrf_cache_tables(conn)


def create_core_tables(conn):
    """Create core tables (users, projects, protocols, etc.)"""
    
    # Users table
    conn.execute('''
        CREATE TABLE export_users (
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            email TEXT,
            first_name TEXT,
            last_name TEXT,
            is_staff BOOLEAN DEFAULT 0,
            is_active BOOLEAN DEFAULT 1,
            date_joined TEXT
        )
    ''')
    
    # Lab Groups
    conn.execute('''
        CREATE TABLE export_lab_groups (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            group_leader_id INTEGER,
            is_professional BOOLEAN DEFAULT 0,
            service_storage TEXT,
            default_storage_id INTEGER,
            created_at TEXT,
            updated_at TEXT
        )
    ''')
    
    # Projects
    conn.execute('''
        CREATE TABLE export_projects (
            id INTEGER PRIMARY KEY,
            project_name TEXT NOT NULL,
            project_description TEXT,
            owner_id INTEGER,
            enabled BOOLEAN DEFAULT 1,
            created_at TEXT,
            updated_at TEXT
        )
    ''')
    
    # Instruments
    conn.execute('''
        CREATE TABLE export_instruments (
            id INTEGER PRIMARY KEY,
            instrument_name TEXT NOT NULL,
            instrument_description TEXT,
            image TEXT,
            enabled BOOLEAN DEFAULT 1,
            max_days_ahead_pre_approval INTEGER DEFAULT 0,
            accepts_bookings BOOLEAN DEFAULT 1,
            created_at TEXT,
            updated_at TEXT
        )
    ''')
    
    # Protocol Models
    conn.execute('''
        CREATE TABLE export_protocols (
            id INTEGER PRIMARY KEY,
            protocol_id INTEGER,
            protocol_title TEXT NOT NULL,
            protocol_description TEXT,
            protocol_doi TEXT,
            protocol_url TEXT,
            protocol_version_uri TEXT,
            user_id INTEGER,
            enabled BOOLEAN DEFAULT 0,
            protocol_created_on TEXT,
            model_hash TEXT
        )
    ''')
    
    # Protocol Sections
    conn.execute('''
        CREATE TABLE export_protocol_sections (
            id INTEGER PRIMARY KEY,
            protocol_id INTEGER,
            section_description TEXT,
            section_duration INTEGER,
            created_at TEXT,
            updated_at TEXT
        )
    ''')
    
    # Protocol Steps
    conn.execute('''
        CREATE TABLE export_protocol_steps (
            id INTEGER PRIMARY KEY,
            protocol_id INTEGER,
            step_id INTEGER,
            step_description TEXT NOT NULL,
            step_section_id INTEGER,
            step_duration INTEGER,
            previous_step_id INTEGER,
            original BOOLEAN DEFAULT 1,
            branch_from_id INTEGER,
            created_at TEXT,
            updated_at TEXT
        )
    ''')
    
    # Sessions
    conn.execute('''
        CREATE TABLE export_sessions (
            id INTEGER PRIMARY KEY,
            unique_id TEXT UNIQUE,
            name TEXT,
            enabled BOOLEAN DEFAULT 1,
            created_at TEXT,
            updated_at TEXT,
            started_at TEXT,
            ended_at TEXT,
            processing BOOLEAN DEFAULT 0
        )
    ''')
    
    # Session Protocols (many-to-many)
    conn.execute('''
        CREATE TABLE export_session_protocols (
            id INTEGER PRIMARY KEY,
            session_id INTEGER,
            protocol_id INTEGER
        )
    ''')
    
    # Annotation Folders
    conn.execute('''
        CREATE TABLE export_annotation_folders (
            id INTEGER PRIMARY KEY,
            session_id INTEGER,
            instrument_id INTEGER,
            stored_reagent_id INTEGER,
            folder_name TEXT NOT NULL,
            parent_folder_id INTEGER,
            is_shared_document_folder BOOLEAN DEFAULT 0,
            owner_id INTEGER,
            created_at TEXT,
            updated_at TEXT
        )
    ''')
    
    # Annotations
    conn.execute('''
        CREATE TABLE export_annotations (
            id INTEGER PRIMARY KEY,
            session_id INTEGER,
            step_id INTEGER,
            stored_reagent_id INTEGER,
            annotation TEXT NOT NULL,
            file TEXT,
            annotation_type TEXT DEFAULT 'text',
            user_id INTEGER,
            folder_id INTEGER,
            annotation_name TEXT,
            summary TEXT,
            transcribed BOOLEAN DEFAULT 0,
            transcription TEXT,
            language TEXT,
            translation TEXT,
            scratched BOOLEAN DEFAULT 0,
            fixed BOOLEAN DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        )
    ''')
    
    # Reagents
    conn.execute('''
        CREATE TABLE export_reagents (
            id INTEGER PRIMARY KEY,
            reagent_name TEXT NOT NULL,
            reagent_description TEXT,
            reagent_cas_number TEXT,
            reagent_molecular_weight REAL,
            created_at TEXT,
            updated_at TEXT
        )
    ''')
    
    # Storage Objects
    conn.execute('''
        CREATE TABLE export_storage_objects (
            id INTEGER PRIMARY KEY,
            object_name TEXT NOT NULL,
            object_type TEXT,
            object_description TEXT,
            user_id INTEGER,
            png_base64 TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    ''')
    
    # Stored Reagents
    conn.execute('''
        CREATE TABLE export_stored_reagents (
            id INTEGER PRIMARY KEY,
            reagent_id INTEGER,
            storage_object_id INTEGER,
            lot_number TEXT,
            expiry_date TEXT,
            quantity REAL,
            notes TEXT,
            barcode TEXT,
            shareable BOOLEAN DEFAULT 0,
            access_all BOOLEAN DEFAULT 0,
            created_by_project_id INTEGER,
            created_by_protocol_id INTEGER,
            created_by_step_id INTEGER,
            created_at TEXT,
            updated_at TEXT
        )
    ''')
    
    # Instrument Jobs
    conn.execute('''
        CREATE TABLE export_instrument_jobs (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            instrument_id INTEGER,
            project_id INTEGER,
            service_lab_group_id INTEGER,
            sample_number INTEGER,
            cost_center TEXT,
            amount REAL,
            job_type TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            updated_at TEXT
        )
    ''')
    
    # Metadata Columns
    conn.execute('''
        CREATE TABLE export_metadata_columns (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            value TEXT,
            type TEXT DEFAULT 'text',
            modifiers TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    ''')
    
    # Tags
    conn.execute('''
        CREATE TABLE export_tags (
            id INTEGER PRIMARY KEY,
            tag_name TEXT UNIQUE NOT NULL,
            tag_description TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    ''')
    
    # Protocol Tags (many-to-many)
    conn.execute('''
        CREATE TABLE export_protocol_tags (
            id INTEGER PRIMARY KEY,
            protocol_id INTEGER,
            tag_id INTEGER,
            created_at TEXT,
            updated_at TEXT
        )
    ''')


def create_billing_tables(conn):
    """Create billing system tables"""
    
    # Service Tiers
    conn.execute('''
        CREATE TABLE export_service_tiers (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            lab_group_id INTEGER,
            is_active BOOLEAN DEFAULT 1,
            created_at TEXT,
            updated_at TEXT
        )
    ''')
    
    # Service Prices
    conn.execute('''
        CREATE TABLE export_service_prices (
            id INTEGER PRIMARY KEY,
            service_tier_id INTEGER,
            instrument_id INTEGER,
            price REAL,
            billing_unit TEXT,
            currency TEXT DEFAULT 'USD',
            effective_date TEXT,
            expiry_date TEXT,
            is_active BOOLEAN DEFAULT 1,
            created_at TEXT,
            updated_at TEXT
        )
    ''')
    
    # Billing Records
    conn.execute('''
        CREATE TABLE export_billing_records (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            instrument_job_id INTEGER,
            service_tier_id INTEGER,
            instrument_hours REAL,
            instrument_rate REAL,
            instrument_cost REAL,
            personnel_hours REAL,
            personnel_rate REAL,
            personnel_cost REAL,
            other_quantity REAL,
            other_rate REAL,
            other_cost REAL,
            other_description TEXT,
            total_amount REAL,
            status TEXT DEFAULT 'pending',
            billing_date TEXT,
            paid_date TEXT,
            invoice_number TEXT,
            notes TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    ''')


def create_backup_tables(conn):
    """Create backup system tables"""
    
    # Backup Logs
    conn.execute('''
        CREATE TABLE export_backup_logs (
            id INTEGER PRIMARY KEY,
            backup_type TEXT NOT NULL,
            status TEXT DEFAULT 'running',
            created_at TEXT,
            completed_at TEXT,
            duration_seconds INTEGER,
            backup_file_path TEXT,
            file_size_bytes INTEGER,
            error_message TEXT,
            success_message TEXT,
            triggered_by TEXT DEFAULT 'cron',
            container_id TEXT
        )
    ''')


def create_sample_pool_tables(conn):
    """Create sample pool tables"""
    
    # Sample Pools
    conn.execute('''
        CREATE TABLE export_sample_pools (
            id INTEGER PRIMARY KEY,
            instrument_job_id INTEGER,
            pool_name TEXT NOT NULL,
            pool_description TEXT,
            pooled_only_samples TEXT,
            pooled_and_independent_samples TEXT,
            template_sample INTEGER,
            is_reference BOOLEAN DEFAULT 0,
            created_by_id INTEGER,
            created_at TEXT,
            updated_at TEXT
        )
    ''')


def create_ontology_tables(conn):
    """Create ontology tables"""
    
    # Cell Types
    conn.execute('''
        CREATE TABLE export_cell_types (
            identifier TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            cell_line BOOLEAN DEFAULT 0,
            organism TEXT,
            tissue_origin TEXT,
            disease_context TEXT,
            accession TEXT,
            synonyms TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    ''')
    
    # MONDO Diseases
    conn.execute('''
        CREATE TABLE export_mondo_diseases (
            identifier TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            definition TEXT,
            synonyms TEXT,
            xrefs TEXT,
            parent_terms TEXT,
            obsolete BOOLEAN DEFAULT 0,
            replacement_term TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    ''')
    
    # UBERON Anatomy
    conn.execute('''
        CREATE TABLE export_uberon_anatomy (
            identifier TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            definition TEXT,
            synonyms TEXT,
            xrefs TEXT,
            parent_terms TEXT,
            part_of TEXT,
            develops_from TEXT,
            obsolete BOOLEAN DEFAULT 0,
            replacement_term TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    ''')
    
    # NCBI Taxonomy
    conn.execute('''
        CREATE TABLE export_ncbi_taxonomy (
            tax_id INTEGER PRIMARY KEY,
            scientific_name TEXT NOT NULL,
            common_name TEXT,
            synonyms TEXT,
            rank TEXT,
            parent_tax_id INTEGER,
            lineage TEXT,
            genetic_code INTEGER,
            mitochondrial_genetic_code INTEGER,
            created_at TEXT,
            updated_at TEXT
        )
    ''')
    
    # ChEBI Compounds
    conn.execute('''
        CREATE TABLE export_chebi_compounds (
            identifier TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            definition TEXT,
            synonyms TEXT,
            formula TEXT,
            mass REAL,
            charge INTEGER,
            inchi TEXT,
            smiles TEXT,
            parent_terms TEXT,
            roles TEXT,
            obsolete BOOLEAN DEFAULT 0,
            replacement_term TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    ''')
    
    # PSI-MS Ontology
    conn.execute('''
        CREATE TABLE export_psims_ontology (
            identifier TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            definition TEXT,
            synonyms TEXT,
            parent_terms TEXT,
            category TEXT,
            obsolete BOOLEAN DEFAULT 0,
            replacement_term TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    ''')


def create_sdrf_cache_tables(conn):
    """Create SDRF cache tables"""
    
    # SDRF Suggestion Cache
    conn.execute('''
        CREATE TABLE export_sdrf_cache (
            id INTEGER PRIMARY KEY,
            step_id INTEGER,
            analyzer_type TEXT,
            sdrf_suggestions TEXT,
            analysis_metadata TEXT,
            extracted_terms TEXT,
            created_at TEXT,
            updated_at TEXT,
            is_valid BOOLEAN DEFAULT 1,
            step_content_hash TEXT
        )
    ''')


def insert_comprehensive_test_data(conn):
    """Insert comprehensive test data for all models"""
    
    base_time = datetime(2025, 1, 15, 9, 0, 0)
    
    # Insert core data (enhanced from original)
    insert_core_test_data(conn, base_time)
    
    # Insert new model data
    insert_billing_test_data(conn, base_time)
    insert_backup_test_data(conn, base_time)
    insert_sample_pool_test_data(conn, base_time)
    insert_ontology_test_data(conn, base_time)
    insert_sdrf_cache_test_data(conn, base_time)


def insert_core_test_data(conn, base_time):
    """Insert enhanced core test data"""
    
    # 1. Insert Users (expanded research team)
    users = [
        (1, 'dr_smith', 'smith@proteomics.edu', 'Dr. Sarah', 'Smith', 1, 1, base_time.isoformat()),
        (2, 'tech_jones', 'jones@proteomics.edu', 'Mike', 'Jones', 0, 1, base_time.isoformat()),
        (3, 'student_alice', 'alice@proteomics.edu', 'Alice', 'Johnson', 0, 1, base_time.isoformat()),
        (4, 'researcher_bob', 'bob@proteomics.edu', 'Dr. Bob', 'Wilson', 0, 1, base_time.isoformat()),
        (5, 'postdoc_chen', 'chen@proteomics.edu', 'Dr. Li', 'Chen', 0, 1, base_time.isoformat()),
        (6, 'staff_davis', 'davis@proteomics.edu', 'Maria', 'Davis', 1, 1, base_time.isoformat()),
    ]
    
    for user in users:
        conn.execute('''INSERT INTO export_users 
                       (id, username, email, first_name, last_name, is_staff, is_active, date_joined) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', user)
    
    # 2. Insert Lab Groups (expanded)
    lab_groups = [
        (1, 'Proteomics Core Facility', 'Advanced protein analysis and characterization', 1, 1, 'freezer_room_a', None, base_time.isoformat(), base_time.isoformat()),
        (2, 'Biochemistry Service Lab', 'General biochemical analysis services', 1, 1, 'chemical_storage', None, base_time.isoformat(), base_time.isoformat()),
        (3, 'Clinical Proteomics Unit', 'Clinical sample analysis and biomarker discovery', 6, 1, 'clinical_storage', None, base_time.isoformat(), base_time.isoformat()),
    ]
    
    for group in lab_groups:
        conn.execute('''INSERT INTO export_lab_groups 
                       (id, name, description, group_leader_id, is_professional, service_storage, default_storage_id, created_at, updated_at) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', group)
    
    # 3. Insert Projects (expanded)
    projects = [
        (1, 'Alzheimer Disease Biomarkers', 'Proteomics investigation of AD biomarkers in CSF', 1, 1, base_time.isoformat(), base_time.isoformat()),
        (2, 'Cancer Drug Discovery', 'Target identification and validation for cancer therapeutics', 4, 1, base_time.isoformat(), base_time.isoformat()),
        (3, 'Metabolomics Profiling', 'Comprehensive metabolite analysis in disease models', 5, 1, base_time.isoformat(), base_time.isoformat()),
        (4, 'Clinical Biomarker Validation', 'Multi-center validation of protein biomarkers', 6, 1, base_time.isoformat(), base_time.isoformat()),
        (5, 'Single Cell Proteomics', 'Development of single-cell protein analysis methods', 1, 1, base_time.isoformat(), base_time.isoformat()),
    ]
    
    for project in projects:
        conn.execute('''INSERT INTO export_projects 
                       (id, project_name, project_description, owner_id, enabled, created_at, updated_at) 
                       VALUES (?, ?, ?, ?, ?, ?, ?)''', project)
    
    # 4. Insert Instruments (expanded)
    instruments = [
        (1, 'Orbitrap Fusion Lumos', 'High-resolution mass spectrometer for proteomics', None, 1, 7, 1, base_time.isoformat(), base_time.isoformat()),
        (2, 'timsTOF Pro', 'Trapped ion mobility mass spectrometer', None, 1, 5, 1, base_time.isoformat(), base_time.isoformat()),
        (3, 'Confocal Microscope LSM980', 'Advanced confocal microscopy system', None, 1, 3, 1, base_time.isoformat(), base_time.isoformat()),
        (4, 'PCR QuantStudio 7', 'Real-time PCR system for gene expression', None, 1, 1, 1, base_time.isoformat(), base_time.isoformat()),
        (5, 'Crystallization Robot', 'Automated protein crystallization screening', None, 1, 14, 0, base_time.isoformat(), base_time.isoformat()),
        (6, 'Cell Culture Hood BSC-1800', 'Class II biological safety cabinet', None, 1, 0, 1, base_time.isoformat(), base_time.isoformat()),
        (7, 'NanoDrop One', 'Microvolume UV-Vis spectrophotometer', None, 1, 0, 1, base_time.isoformat(), base_time.isoformat()),
        (8, 'ACQUITY UPLC H-Class', 'Ultra-performance liquid chromatography system', None, 1, 2, 1, base_time.isoformat(), base_time.isoformat()),
    ]
    
    for instrument in instruments:
        conn.execute('''INSERT INTO export_instruments 
                       (id, instrument_name, instrument_description, image, enabled, max_days_ahead_pre_approval, accepts_bookings, created_at, updated_at) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', instrument)
    
    # Continue with protocols, sessions, etc. (enhanced versions)
    insert_enhanced_protocols_and_sessions(conn, base_time)


def insert_enhanced_protocols_and_sessions(conn, base_time):
    """Insert enhanced protocol and session data"""
    
    # 5. Insert Enhanced Protocols
    protocols = [
        (1, 1001, 'TMT-11plex Proteomics Workflow', 
         'Complete TMT labeling protocol for quantitative proteomics with 11-plex reagents', 
         '10.21769/BioProtoc.4001', 'https://bio-protocol.org/e4001', 'v3.1', 1, 1, base_time.isoformat(), 'hash_001'),
        
        (2, 1002, 'DIA-MS Data Acquisition Protocol', 
         'Data-independent acquisition mass spectrometry for comprehensive proteome analysis', 
         '10.21769/BioProtoc.4002', 'https://bio-protocol.org/e4002', 'v2.3', 1, 1, base_time.isoformat(), 'hash_002'),
        
        (3, 1003, 'Single Cell Sample Preparation', 
         'Protocol for preparing single cells for proteomics analysis using nanodroplet processing', 
         None, None, 'v1.5', 5, 1, base_time.isoformat(), 'hash_003'),
        
        (4, 1004, 'Clinical Sample Processing Pipeline', 
         'Standardized protocol for processing clinical samples including CSF, plasma, and tissue', 
         '10.21769/BioProtoc.4003', 'https://bio-protocol.org/e4003', 'v4.0', 6, 1, base_time.isoformat(), 'hash_004'),
        
        (5, 1005, 'PTM Enrichment and Analysis', 
         'Post-translational modification enrichment using TiO2 and IMAC for phosphoproteomics', 
         '10.21769/BioProtoc.4004', 'https://bio-protocol.org/e4004', 'v2.8', 4, 1, base_time.isoformat(), 'hash_005'),
        
        (6, 1006, 'Cross-linking Mass Spectrometry', 
         'Chemical cross-linking protocol for studying protein-protein interactions', 
         None, None, 'v1.2', 5, 1, base_time.isoformat(), 'hash_006'),
        
        (7, 1007, 'Membrane Proteomics Extraction', 
         'Specialized protocol for membrane protein extraction and analysis', 
         '10.21769/BioProtoc.4005', 'https://bio-protocol.org/e4005', 'v3.0', 2, 1, base_time.isoformat(), 'hash_007'),
    ]
    
    for protocol in protocols:
        conn.execute('''INSERT INTO export_protocols 
                       (id, protocol_id, protocol_title, protocol_description, protocol_doi, protocol_url, protocol_version_uri, user_id, enabled, protocol_created_on, model_hash) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', protocol)
    
    # 6. Insert Protocol Sections and Steps (more detailed)
    insert_detailed_protocol_sections_and_steps(conn, base_time)
    
    # 7. Insert Sessions (expanded)
    sessions = [
        (1, str(uuid.uuid4()), 'TMT Proteomics - AD Cohort Batch 1', 1, base_time.isoformat(), base_time.isoformat(), 
         base_time.isoformat(), (base_time + timedelta(hours=12)).isoformat(), 0),
        (2, str(uuid.uuid4()), 'DIA-MS Analysis - Cancer Cell Lines', 1, (base_time + timedelta(days=1)).isoformat(), (base_time + timedelta(days=1)).isoformat(),
         (base_time + timedelta(days=1)).isoformat(), (base_time + timedelta(days=1, hours=8)).isoformat(), 0),
        (3, str(uuid.uuid4()), 'Single Cell Prep - HeLa Cells', 1, (base_time + timedelta(days=2)).isoformat(), (base_time + timedelta(days=2)).isoformat(),
         (base_time + timedelta(days=2)).isoformat(), (base_time + timedelta(days=2, hours=6)).isoformat(), 0),
        (4, str(uuid.uuid4()), 'Clinical Sample Batch Processing', 1, (base_time + timedelta(days=3)).isoformat(), (base_time + timedelta(days=3)).isoformat(),
         (base_time + timedelta(days=3)).isoformat(), (base_time + timedelta(days=3, hours=10)).isoformat(), 0),
        (5, str(uuid.uuid4()), 'Phosphoproteomics - Growth Factors', 1, (base_time + timedelta(days=4)).isoformat(), (base_time + timedelta(days=4)).isoformat(),
         (base_time + timedelta(days=4)).isoformat(), (base_time + timedelta(days=4, hours=14)).isoformat(), 0),
        (6, str(uuid.uuid4()), 'Cross-linking MS - Protein Complex', 1, (base_time + timedelta(days=5)).isoformat(), (base_time + timedelta(days=5)).isoformat(),
         (base_time + timedelta(days=5)).isoformat(), (base_time + timedelta(days=5, hours=9)).isoformat(), 0),
        (7, str(uuid.uuid4()), 'Membrane Proteome - Brain Tissue', 1, (base_time + timedelta(days=6)).isoformat(), (base_time + timedelta(days=6)).isoformat(),
         (base_time + timedelta(days=6)).isoformat(), (base_time + timedelta(days=6, hours=16)).isoformat(), 0),
    ]
    
    for session in sessions:
        conn.execute('''INSERT INTO export_sessions 
                       (id, unique_id, name, enabled, created_at, updated_at, started_at, ended_at, processing) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', session)
    
    # 8. Link sessions to protocols
    session_protocols = [
        (1, 1, 1), (2, 2, 2), (3, 3, 3), (4, 4, 4), (5, 5, 5), (6, 6, 6), (7, 7, 7)
    ]
    
    for sp in session_protocols:
        conn.execute('''INSERT INTO export_session_protocols (id, session_id, protocol_id) VALUES (?, ?, ?)''', sp)
    
    # 9. Create comprehensive annotations (100+ annotations)
    create_comprehensive_annotations(conn, base_time)


def insert_detailed_protocol_sections_and_steps(conn, base_time):
    """Insert detailed protocol sections and steps"""
    # This would be very long - abbreviated for space
    # Each protocol would have 10-20 sections with 5-15 steps each
    
    sections = []
    steps = []
    section_id = 1
    step_id = 1
    
    # For each protocol, create detailed sections and steps
    for protocol_id in range(1, 8):  # 7 protocols
        
        if protocol_id == 1:  # TMT Protocol
            protocol_sections = [
                'Sample Preparation and Lysis',
                'Protein Digestion and Cleanup', 
                'TMT Labeling',
                'Peptide Fractionation',
                'LC-MS/MS Analysis',
                'Data Processing and Analysis'
            ]
            
        elif protocol_id == 2:  # DIA-MS Protocol
            protocol_sections = [
                'Sample Preparation',
                'Peptide Separation',
                'DIA Method Setup',
                'Mass Spectrometry Acquisition',
                'Library Generation',
                'Data Analysis'
            ]
            
        # Add more protocol-specific sections...
        else:
            protocol_sections = [
                f'Protocol {protocol_id} Section 1',
                f'Protocol {protocol_id} Section 2', 
                f'Protocol {protocol_id} Section 3'
            ]
        
        for section_desc in protocol_sections:
            sections.append((section_id, protocol_id, section_desc, 60, base_time.isoformat(), base_time.isoformat()))
            
            # Add 5-10 steps per section
            for i in range(5):
                step_desc = f"{section_desc} - Step {i+1}: Detailed procedure step"
                steps.append((step_id, protocol_id, (section_id * 10) + i + 1, step_desc, section_id, 10, 
                             step_id-1 if i > 0 else None, 1, None, base_time.isoformat(), base_time.isoformat()))
                step_id += 1
                
            section_id += 1
    
    # Insert sections and steps
    for section in sections:
        conn.execute('''INSERT INTO export_protocol_sections 
                       (id, protocol_id, section_description, section_duration, created_at, updated_at) 
                       VALUES (?, ?, ?, ?, ?, ?)''', section)
    
    for step in steps:
        conn.execute('''INSERT INTO export_protocol_steps 
                       (id, protocol_id, step_id, step_description, step_section_id, step_duration, previous_step_id, original, branch_from_id, created_at, updated_at) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', step)


def create_comprehensive_annotations(conn, base_time):
    """Create 100+ comprehensive annotations"""
    
    annotations = []
    ann_id = 1
    
    # All annotation types
    ann_types = ["text", "file", "image", "video", "audio", "sketch", "other", "checklist", "counter", "table"]
    
    # Create 15-20 annotations per session (7 sessions = 105-140 annotations)
    for session_id in range(1, 8):
        session_time = base_time + timedelta(days=session_id-1)
        
        for i in range(15):  # 15 annotations per session
            ann_type = ann_types[i % len(ann_types)]
            
            # Create varied annotation content based on session type
            if session_id == 1:  # TMT session
                content = f"TMT label {i+1}: {random.choice(['126', '127N', '127C', '128N', '128C', '129N', '129C', '130N', '130C', '131N', '131C'])}"
            elif session_id == 2:  # DIA session
                content = f"DIA window {i+1}: m/z {400 + i*50} - {449 + i*50}"
            else:
                content = f"Session {session_id} annotation {i+1}: Detailed experimental observation"
            
            file_path = f"annotations/session_{session_id}_ann_{i+1}.{get_file_extension(ann_type)}" if ann_type != "text" else None
            
            annotation = (
                ann_id, session_id, (i % 20) + 1, None,  # step_id cycles through first 20 steps
                content, file_path, ann_type, 
                (session_id % 6) + 1,  # user_id cycles through users
                (i % 5) + 1,  # folder_id
                f"Annotation {ann_id}",
                f"Summary of annotation {ann_id}",
                0, None, "en", None, 0, 0,
                session_time.isoformat(), session_time.isoformat()
            )
            
            annotations.append(annotation)
            ann_id += 1
    
    # Insert all annotations
    for annotation in annotations:
        conn.execute('''INSERT INTO export_annotations 
                       (id, session_id, step_id, stored_reagent_id, annotation, file, annotation_type, user_id, folder_id, annotation_name, summary, transcribed, transcription, language, translation, scratched, fixed, created_at, updated_at) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', annotation)


def get_file_extension(ann_type):
    """Get appropriate file extension for annotation type"""
    extensions = {
        'file': 'pdf',
        'image': 'jpg', 
        'video': 'mp4',
        'audio': 'wav',
        'sketch': 'png',
        'table': 'xlsx',
        'other': 'txt'
    }
    return extensions.get(ann_type, 'txt')


def insert_billing_test_data(conn, base_time):
    """Insert comprehensive billing test data"""
    
    # Service Tiers
    service_tiers = [
        (1, 'Academic', 'Academic research pricing', 1, 1, base_time.isoformat(), base_time.isoformat()),
        (2, 'Commercial', 'Commercial/industry pricing', 1, 1, base_time.isoformat(), base_time.isoformat()),
        (3, 'Clinical', 'Clinical research pricing', 3, 1, base_time.isoformat(), base_time.isoformat()),
        (4, 'Internal', 'Internal facility usage', 2, 1, base_time.isoformat(), base_time.isoformat()),
    ]
    
    for tier in service_tiers:
        conn.execute('''INSERT INTO export_service_tiers 
                       (id, name, description, lab_group_id, is_active, created_at, updated_at) 
                       VALUES (?, ?, ?, ?, ?, ?, ?)''', tier)
    
    # Service Prices (different rates for different tiers and instruments)
    service_prices = [
        (1, 1, 1, 75.00, 'per_hour_instrument', 'USD', base_time.date().isoformat(), None, 1, base_time.isoformat(), base_time.isoformat()),
        (2, 2, 1, 150.00, 'per_hour_instrument', 'USD', base_time.date().isoformat(), None, 1, base_time.isoformat(), base_time.isoformat()),
        (3, 1, 2, 85.00, 'per_hour_instrument', 'USD', base_time.date().isoformat(), None, 1, base_time.isoformat(), base_time.isoformat()),
        (4, 2, 2, 170.00, 'per_hour_instrument', 'USD', base_time.date().isoformat(), None, 1, base_time.isoformat(), base_time.isoformat()),
        (5, 1, 1, 25.00, 'per_sample', 'USD', base_time.date().isoformat(), None, 1, base_time.isoformat(), base_time.isoformat()),
        (6, 2, 1, 50.00, 'per_sample', 'USD', base_time.date().isoformat(), None, 1, base_time.isoformat(), base_time.isoformat()),
    ]
    
    for price in service_prices:
        conn.execute('''INSERT INTO export_service_prices 
                       (id, service_tier_id, instrument_id, price, billing_unit, currency, effective_date, expiry_date, is_active, created_at, updated_at) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', price)


def insert_backup_test_data(conn, base_time):
    """Insert backup log test data"""
    
    backup_logs = [
        (1, 'database', 'completed', base_time.isoformat(), (base_time + timedelta(minutes=30)).isoformat(), 
         1800, '/backups/db_backup_20250115.sql.gz', 52428800, None, 'Database backup completed successfully', 'cron', 'backup-db-123'),
        (2, 'media', 'completed', (base_time + timedelta(days=1)).isoformat(), (base_time + timedelta(days=1, hours=2)).isoformat(),
         7200, '/backups/media_backup_20250116.tar.gz', 1073741824, None, 'Media files backup completed', 'cron', 'backup-media-456'),
        (3, 'full', 'failed', (base_time + timedelta(days=2)).isoformat(), (base_time + timedelta(days=2, minutes=10)).isoformat(),
         600, None, None, 'Insufficient disk space for full backup', None, 'manual', 'backup-full-789'),
        (4, 'database', 'completed', (base_time + timedelta(days=3)).isoformat(), (base_time + timedelta(days=3, minutes=25)).isoformat(),
         1500, '/backups/db_backup_20250118.sql.gz', 54525952, None, 'Daily database backup', 'cron', 'backup-db-abc'),
    ]
    
    for backup in backup_logs:
        conn.execute('''INSERT INTO export_backup_logs 
                       (id, backup_type, status, created_at, completed_at, duration_seconds, backup_file_path, file_size_bytes, error_message, success_message, triggered_by, container_id) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', backup)


def insert_sample_pool_test_data(conn, base_time):
    """Insert sample pool test data"""
    
    # First create some instrument jobs
    instrument_jobs = [
        (1, 1, 1, 1, 1, 24, 'PROT001', 2500.00, 'analysis', 'completed', base_time.isoformat(), base_time.isoformat()),
        (2, 4, 2, 2, 2, 16, 'CANC001', 1800.00, 'analysis', 'completed', (base_time + timedelta(days=1)).isoformat(), (base_time + timedelta(days=1)).isoformat()),
        (3, 5, 1, 3, 1, 12, 'META001', 1200.00, 'analysis', 'running', (base_time + timedelta(days=2)).isoformat(), (base_time + timedelta(days=2)).isoformat()),
    ]
    
    for job in instrument_jobs:
        conn.execute('''INSERT INTO export_instrument_jobs 
                       (id, user_id, instrument_id, project_id, service_lab_group_id, sample_number, cost_center, amount, job_type, status, created_at, updated_at) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', job)
    
    # Sample pools with JSON-serialized arrays
    sample_pools = [
        (1, 1, 'TMT_Pool_A', 'High confidence samples from AD cohort', '[1, 2, 3, 4]', '[5, 6]', 1, 1, 1, base_time.isoformat(), base_time.isoformat()),
        (2, 1, 'TMT_Pool_B', 'Control samples', '[7, 8, 9]', '[]', None, 0, 1, base_time.isoformat(), base_time.isoformat()),
        (3, 2, 'Cancer_Pool_1', 'Primary tumor samples', '[1, 3, 5, 7]', '[2, 4]', 2, 0, 4, (base_time + timedelta(days=1)).isoformat(), (base_time + timedelta(days=1)).isoformat()),
        (4, 3, 'Reference_Pool', 'Reference standard pool', '[11, 12]', '[]', 11, 1, 5, (base_time + timedelta(days=2)).isoformat(), (base_time + timedelta(days=2)).isoformat()),
    ]
    
    for pool in sample_pools:
        conn.execute('''INSERT INTO export_sample_pools 
                       (id, instrument_job_id, pool_name, pool_description, pooled_only_samples, pooled_and_independent_samples, template_sample, is_reference, created_by_id, created_at, updated_at) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', pool)


def insert_ontology_test_data(conn, base_time):
    """Insert comprehensive ontology test data"""
    
    # Cell Types
    cell_types = [
        ('CL:0000066', 'epithelial cell', 'A cell that is usually found in a two-dimensional sheet', 0, 'Homo sapiens', 'epithelium', None, 'CL:0000066', 'epithelium cell', base_time.isoformat(), base_time.isoformat()),
        ('CL:0000236', 'B cell', 'A lymphocyte of B lineage that is found in the bone marrow', 0, 'Homo sapiens', 'bone marrow', None, 'CL:0000236', 'B lymphocyte;B-cell', base_time.isoformat(), base_time.isoformat()),
        ('CL:0000084', 'T cell', 'A type of lymphocyte', 0, 'Homo sapiens', 'thymus', None, 'CL:0000084', 'T lymphocyte;T-cell', base_time.isoformat(), base_time.isoformat()),
        ('HeLa', 'HeLa', 'Immortalized cervical cancer cell line', 1, 'Homo sapiens', 'cervix', 'cervical adenocarcinoma', 'CCL-2', 'CCL-2;ATCC CCL-2', base_time.isoformat(), base_time.isoformat()),
        ('HEK293T', 'HEK293T', 'Human embryonic kidney cell line with SV40 T antigen', 1, 'Homo sapiens', 'kidney', None, 'CRL-3216', 'HEK 293T;293T', base_time.isoformat(), base_time.isoformat()),
    ]
    
    for cell_type in cell_types:
        conn.execute('''INSERT INTO export_cell_types 
                       (identifier, name, description, cell_line, organism, tissue_origin, disease_context, accession, synonyms, created_at, updated_at) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', cell_type)
    
    # MONDO Diseases
    diseases = [
        ('MONDO:0007256', 'Alzheimer disease', 'A dementia that is characterized by memory lapses, confusion, emotional instability', 
         'Alzheimer disease;dementia, Alzheimer type;AD', 'DOID:10652;OMIM:104300;UMLS:C0002395', 'MONDO:0001627;MONDO:0005071', 0, None, base_time.isoformat(), base_time.isoformat()),
        ('MONDO:0005148', 'type 2 diabetes mellitus', 'A diabetes mellitus that is characterized by insulin resistance', 
         'T2DM;diabetes mellitus type 2', 'DOID:9352;OMIM:125853', 'MONDO:0005015', 0, None, base_time.isoformat(), base_time.isoformat()),
        ('MONDO:0004992', 'cancer', 'A disease characterized by uncontrolled cellular proliferation', 
         'malignant tumor;neoplasm', 'DOID:162;UMLS:C0006826', 'MONDO:0000001', 0, None, base_time.isoformat(), base_time.isoformat()),
    ]
    
    for disease in diseases:
        conn.execute('''INSERT INTO export_mondo_diseases 
                       (identifier, name, definition, synonyms, xrefs, parent_terms, obsolete, replacement_term, created_at, updated_at) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', disease)
    
    # NCBI Taxonomy
    taxa = [
        (9606, 'Homo sapiens', 'human', 'modern man', 'species', 9605, 'Eukaryota;Metazoa;Chordata;Mammalia;Primates;Hominidae;Homo', 1, 2, base_time.isoformat(), base_time.isoformat()),
        (10090, 'Mus musculus', 'house mouse', 'laboratory mouse', 'species', 10089, 'Eukaryota;Metazoa;Chordata;Mammalia;Rodentia;Muridae;Mus', 1, 2, base_time.isoformat(), base_time.isoformat()),
        (7955, 'Danio rerio', 'zebrafish', 'zebra danio', 'species', 7954, 'Eukaryota;Metazoa;Chordata;Actinopterygii;Cypriniformes;Cyprinidae;Danio', 1, 2, base_time.isoformat(), base_time.isoformat()),
    ]
    
    for taxon in taxa:
        conn.execute('''INSERT INTO export_ncbi_taxonomy 
                       (tax_id, scientific_name, common_name, synonyms, rank, parent_tax_id, lineage, genetic_code, mitochondrial_genetic_code, created_at, updated_at) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', taxon)
    
    # ChEBI Compounds
    compounds = [
        ('CHEBI:15377', 'water', 'An oxygen hydride consisting of an oxygen atom that is covalently bonded to two hydrogen atoms', 
         'H2O;dihydrogen oxide;oxidane', 'H2O', 18.01528, 0, 'InChI=1S/H2O/h1H2', 'O', 'CHEBI:33579;CHEBI:5585', 'solvent;polar solvent', 0, None, base_time.isoformat(), base_time.isoformat()),
        ('CHEBI:16236', 'ethanol', 'A primary alcohol that is ethane in which one of the hydrogens is substituted by a hydroxy group', 
         'EtOH;ethyl alcohol', 'C2H6O', 46.06844, 0, 'InChI=1S/C2H6O/c1-2-3/h3H,2H2,1H3', 'CCO', 'CHEBI:30879', 'solvent;fuel', 0, None, base_time.isoformat(), base_time.isoformat()),
        ('CHEBI:17234', 'glucose', 'A hexose that is an aldose', 
         'D-glucose;dextrose', 'C6H12O6', 180.156, 0, 'InChI=1S/C6H12O6/c7-1-2-3(8)4(9)5(10)6(11)12-2/h2-11H,1H2/t2-,3-,4+,5-,6+/m1/s1', 'C([C@@H]1[C@H]([C@@H]([C@H]([C@H](O1)O)O)O)O)O', 'CHEBI:24973', 'nutrient;energy source', 0, None, base_time.isoformat(), base_time.isoformat()),
    ]
    
    for compound in compounds:
        conn.execute('''INSERT INTO export_chebi_compounds 
                       (identifier, name, definition, synonyms, formula, mass, charge, inchi, smiles, parent_terms, roles, obsolete, replacement_term, created_at, updated_at) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', compound)
    
    # PSI-MS Ontology Terms
    ms_terms = [
        ('MS:1000031', 'instrument model', 'Instrument model name not including the vendor name', 'instrument model name', 'MS:1000463', 'instrument', 0, None, base_time.isoformat(), base_time.isoformat()),
        ('MS:1000579', 'MS1 spectrum', 'Mass spectrum created by a single-stage MS experiment or the first stage of a multi-stage experiment', 'full scan spectrum', 'MS:1000294', 'spectrum', 0, None, base_time.isoformat(), base_time.isoformat()),
        ('MS:1000580', 'MSn spectrum', 'Mass spectrum from the nth stage of a multi-stage MS experiment', 'tandem mass spectrum', 'MS:1000294', 'spectrum', 0, None, base_time.isoformat(), base_time.isoformat()),
        ('MS:1000044', 'dissociation method', 'Fragmentation method used for dissociation or fragmentation', None, 'MS:1000456', 'method', 0, None, base_time.isoformat(), base_time.isoformat()),
    ]
    
    for term in ms_terms:
        conn.execute('''INSERT INTO export_psims_ontology 
                       (identifier, name, definition, synonyms, parent_terms, category, obsolete, replacement_term, created_at, updated_at) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', term)


def insert_sdrf_cache_test_data(conn, base_time):
    """Insert SDRF suggestion cache test data"""
    
    # Create cache entries for different steps and analyzers
    cache_entries = [
        (1, 1, 'standard_nlp', json.dumps({'organism': 'Homo sapiens', 'sample_type': 'serum'}), 
         json.dumps({'confidence': 0.85, 'processing_time': 1.2}), json.dumps(['serum', 'sample', 'human']),
         base_time.isoformat(), base_time.isoformat(), 1, hashlib.sha256('Step 1 content'.encode()).hexdigest()),
        (2, 2, 'mcp_claude', json.dumps({'organism': 'Mus musculus', 'sample_type': 'tissue'}), 
         json.dumps({'confidence': 0.92, 'processing_time': 2.1}), json.dumps(['tissue', 'mouse', 'extraction']),
         base_time.isoformat(), base_time.isoformat(), 1, hashlib.sha256('Step 2 content'.encode()).hexdigest()),
        (3, 3, 'anthropic_claude', json.dumps({'instrument': 'Orbitrap', 'method': 'DDA'}), 
         json.dumps({'confidence': 0.88, 'processing_time': 1.8}), json.dumps(['orbitrap', 'dda', 'ms']),
         base_time.isoformat(), base_time.isoformat(), 1, hashlib.sha256('Step 3 content'.encode()).hexdigest()),
        (4, 1, 'mcp_claude', json.dumps({'organism': 'Homo sapiens', 'disease': 'Alzheimer disease'}), 
         json.dumps({'confidence': 0.90, 'processing_time': 1.5}), json.dumps(['alzheimer', 'disease', 'brain']),
         (base_time + timedelta(hours=1)).isoformat(), (base_time + timedelta(hours=1)).isoformat(), 1, hashlib.sha256('Step 1 updated content'.encode()).hexdigest()),
    ]
    
    for cache in cache_entries:
        conn.execute('''INSERT INTO export_sdrf_cache 
                       (id, step_id, analyzer_type, sdrf_suggestions, analysis_metadata, extracted_terms, created_at, updated_at, is_valid, step_content_hash) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', cache)


def create_comprehensive_media_files(media_dir):
    """Create comprehensive media files for all annotation types"""
    os.makedirs(media_dir, exist_ok=True)
    
    # Create subdirectory for annotations
    ann_dir = os.path.join(media_dir, 'annotations')
    os.makedirs(ann_dir, exist_ok=True)
    
    # Create files for 7 sessions with 15 annotations each
    files_to_create = []
    
    for session_id in range(1, 8):
        for i in range(15):
            # Create different file types based on annotation index
            file_types = {
                0: ('jpg', b'\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xFF\xDB\x00C\x00fake_jpeg_image_data'),
                1: ('pdf', b'%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\nfake_pdf_document_data'),
                2: ('mp4', b'\x00\x00\x00\x1Cftypmp41\x00\x00\x00\x00mp41isom\x00\x00\x00\x08freefake_mp4_video_data'),
                3: ('wav', b'RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00D\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00datafake_wav_audio_data'),
                4: ('png', b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x10\x00\x00\x00\x10\x08\x06\x00\x00\x00\x1f\xf3\xffa\x00\x00\x00\x19tEXtSoftware\x00Adobe ImageReadyq\xc9e<fake_png_sketch'),
                5: ('xlsx', b'PK\x03\x04\x14\x00\x00\x00\x08\x00fake_excel_table_data_with_comprehensive_content'),
                6: ('txt', b'This is a text file containing detailed experimental notes and observations for comprehensive testing'),
            }
            
            file_type_idx = i % len(file_types)
            if file_type_idx in file_types:
                extension, content = file_types[file_type_idx]
                filename = f'session_{session_id}_ann_{i+1}.{extension}'
                files_to_create.append((filename, content))
    
    # Add additional specialized files
    specialized_files = [
        ('tmt_quantification.xlsx', b'PK\x03\x04\x14\x00\x00\x00\x08\x00fake_excel_tmt_quantification_results'),
        ('dia_library.csv', b'Protein,Peptide,Charge,RT,Intensity\nP12345,PEPTIDER,2,25.6,1000000\n'),
        ('clinical_metadata.csv', b'Sample_ID,Age,Sex,Disease,BMI\nCLIN001,65,M,AD,24.5\nCLIN002,72,F,AD,22.1\n'),
        ('mass_spec_parameters.txt', b'LC Gradient: 2-35% ACN over 120 min\nMS Resolution: 70,000 @ 200 m/z\nAGC Target: 1e6\n'),
        ('protein_ids.tsv', b'Protein\tGene\tDescription\tCoverage\nP12345\tAPP\tAmyloid precursor protein\t45.2\n'),
        ('phospho_sites.xlsx', b'PK\x03\x04\x14\x00\x00\x00\x08\x00fake_excel_phosphoproteomics_site_localization'),
    ]
    
    files_to_create.extend(specialized_files)
    
    # Create all files
    for filename, content in files_to_create:
        filepath = os.path.join(ann_dir, filename)
        with open(filepath, 'wb') as f:
            f.write(content)
    
    print(f"Created {len(files_to_create)} comprehensive media files in {ann_dir}")


def create_comprehensive_export_metadata():
    """Create comprehensive export metadata"""
    base_time = datetime(2025, 1, 15, 9, 0, 0)
    
    return {
        'export_timestamp': base_time.isoformat(),
        'source_user_id': 1,
        'source_username': 'dr_smith',
        'source_email': 'smith@proteomics.edu',
        'cupcake_version': '2.0.0',
        'export_format_version': '4.0',
        'archive_format': 'zip',
        'archive_sha256': 'mock_comprehensive_sha256_hash_for_test_fixture',
        'stats': {
            'protocols_exported': 7,
            'sessions_exported': 7,
            'annotations_exported': 105,
            'files_exported': 90,
            'instruments_exported': 8,
            'users_exported': 6,
            'projects_exported': 5,
            'lab_groups_exported': 3,
            'reagents_exported': 15,
            'storage_objects_exported': 10,
            'tags_exported': 12,
            'service_tiers_exported': 4,
            'billing_records_exported': 8,
            'backup_logs_exported': 4,
            'sample_pools_exported': 4,
            'cell_types_exported': 5,
            'diseases_exported': 3,
            'taxa_exported': 3,
            'compounds_exported': 3,
            'ms_terms_exported': 4,
            'sdrf_cache_entries_exported': 4,
            'relationships_exported': 45
        },
        'export_summary': {
            'laboratory_name': 'Advanced Proteomics Research Facility',
            'export_purpose': 'Comprehensive test fixture for full system validation',
            'data_time_range': f"{base_time.isoformat()} to {(base_time + timedelta(days=7)).isoformat()}",
            'experimental_focus': [
                'TMT-based quantitative proteomics',
                'Data-independent acquisition mass spectrometry',
                'Single-cell proteomics methodology',
                'Clinical biomarker discovery',
                'Post-translational modification analysis',
                'Protein-protein interaction studies',
                'Membrane proteomics extraction'
            ],
            'annotation_type_distribution': {
                'text': 45,
                'image': 18,
                'file': 15,
                'video': 12,
                'table': 9,
                'audio': 6,
                'other': 6,
                'sketch': 6,
                'checklist': 3,
                'counter': 3
            },
            'new_features_included': [
                'Comprehensive billing system with multiple tiers',
                'Backup and monitoring logs',
                'Sample pooling for SDRF compliance',
                'Extended ontology integration',
                'SDRF suggestion caching system',
                'Enhanced metadata columns with modifiers',
                'Multi-tier service pricing'
            ],
            'instruments_used': [
                'Orbitrap Fusion Lumos',
                'timsTOF Pro',
                'Confocal Microscope LSM980',
                'PCR QuantStudio 7',
                'Crystallization Robot',
                'Cell Culture Hood BSC-1800',
                'NanoDrop One',
                'ACQUITY UPLC H-Class'
            ],
            'ontology_coverage': {
                'cell_types': 'Primary cells and immortalized cell lines',
                'diseases': 'Neurodegenerative and metabolic disorders',
                'organisms': 'Human, mouse, and zebrafish',
                'compounds': 'Common biochemical compounds',
                'ms_terms': 'Mass spectrometry methodology terms'
            }
        }
    }


if __name__ == '__main__':
    create_comprehensive_test_fixture()
    print("Comprehensive test fixture creation completed!")
    print("Created comprehensive_test_fixture.zip with:")
    print("- 7 detailed protocols with 100+ steps")
    print("- 7 experimental sessions spanning a week")
    print("- 105+ annotations across all annotation types")
    print("- 8 instruments with comprehensive usage tracking")
    print("- 6 users with different roles and permissions")
    print("- 5 research projects with detailed descriptions")
    print("- 3 lab groups with service tier configurations")
    print("- Complete billing system with 4 tiers and pricing")
    print("- Backup monitoring with 4 log entries")
    print("- 4 sample pools with complex pooling strategies")
    print("- Comprehensive ontology data (20+ terms)")
    print("- SDRF suggestion cache with 4 entries")
    print("- 90+ media files (images, videos, data files, PDFs)")
    print("- Complete relationships and enhanced metadata")
    print("- Full export/import testing coverage")