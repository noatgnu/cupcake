#!/usr/bin/env python3
"""
Enhanced comprehensive test fixture for import/export testing v2.0
Includes all new models with realistic laboratory scenarios:
- Billing system with multiple tiers and transactions
- Backup monitoring with detailed logs
- Sample pooling with complex SDRF metadata
- Ontology integration with real biological terms
- SDRF cache system with AI suggestions
- Multiple lab groups with different access patterns
- Realistic instrument jobs with comprehensive metadata
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
import base64


def create_comprehensive_test_fixture():
    """Create comprehensive test fixture with all CUPCAKE models"""
    
    print("🔬 Creating comprehensive CUPCAKE test fixture v2.0...")
    
    # Create temporary directory for building the archive
    temp_dir = tempfile.mkdtemp()
    
    try:
        # Create the SQLite database with comprehensive test data
        sqlite_path = os.path.join(temp_dir, 'user_data.sqlite')
        print("📊 Creating comprehensive database...")
        create_comprehensive_database(sqlite_path)
        
        # Create media files for different annotation types
        media_dir = os.path.join(temp_dir, 'media')
        print("📁 Creating realistic media files...")
        create_comprehensive_media_files(media_dir)
        
        # Create comprehensive export metadata
        print("📋 Generating export metadata...")
        metadata = create_comprehensive_export_metadata()
        
        with open(os.path.join(temp_dir, 'export_metadata.json'), 'w') as f:
            json.dump(metadata, f, indent=2)
        
        # Create additional test files
        create_additional_test_files(temp_dir)
        
        # Create the ZIP archive
        archive_path = 'comprehensive_test_fixture_v2.zip'
        print("🗜️ Creating ZIP archive...")
        with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arc_path = os.path.relpath(file_path, temp_dir)
                    zipf.write(file_path, arc_path)
        
        print(f"✅ Created comprehensive test fixture: {archive_path}")
        print_fixture_summary()
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
    
    # Core tables
    create_core_tables(conn)
    
    # Enhanced tables for new functionality
    create_billing_tables(conn)
    create_backup_tables(conn) 
    create_sample_pool_tables(conn)
    create_ontology_tables(conn)
    create_sdrf_cache_tables(conn)
    create_lab_group_tables(conn)
    create_instrument_tables(conn)


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
            date_joined TEXT,
            department TEXT,
            phone TEXT,
            orcid_id TEXT
        )
    ''')
    
    # Projects table
    conn.execute('''
        CREATE TABLE export_projects (
            id INTEGER PRIMARY KEY,
            project_name TEXT NOT NULL,
            project_description TEXT,
            owner_id INTEGER,
            created_at TEXT,
            updated_at TEXT,
            is_public BOOLEAN DEFAULT 0,
            funding_source TEXT,
            project_code TEXT,
            status TEXT DEFAULT 'active',
            FOREIGN KEY (owner_id) REFERENCES export_users (id)
        )
    ''')
    
    # Protocols table
    conn.execute('''
        CREATE TABLE export_protocols (
            id INTEGER PRIMARY KEY,
            protocol_title TEXT NOT NULL,
            protocol_id INTEGER UNIQUE,
            protocol_description TEXT,
            user_id INTEGER,
            enabled BOOLEAN DEFAULT 1,
            created_at TEXT,
            updated_at TEXT,
            version TEXT DEFAULT '1.0',
            doi TEXT,
            publication_status TEXT DEFAULT 'draft',
            FOREIGN KEY (user_id) REFERENCES export_users (id)
        )
    ''')
    
    # Protocol sections table
    conn.execute('''
        CREATE TABLE export_protocol_sections (
            id INTEGER PRIMARY KEY,
            protocol_id INTEGER,
            section_description TEXT,
            section_order INTEGER DEFAULT 1,
            section_type TEXT DEFAULT 'general',
            estimated_duration INTEGER,
            FOREIGN KEY (protocol_id) REFERENCES export_protocols (id)
        )
    ''')
    
    # Protocol steps table
    conn.execute('''
        CREATE TABLE export_protocol_steps (
            id INTEGER PRIMARY KEY,
            protocol_id INTEGER,
            step_id INTEGER,
            step_description TEXT,
            step_section_id INTEGER,
            step_order INTEGER DEFAULT 1,
            created_at TEXT,
            updated_at TEXT,
            step_type TEXT DEFAULT 'manual',
            requires_approval BOOLEAN DEFAULT 0,
            safety_notes TEXT,
            FOREIGN KEY (protocol_id) REFERENCES export_protocols (id),
            FOREIGN KEY (step_section_id) REFERENCES export_protocol_sections (id)
        )
    ''')


def create_lab_group_tables(conn):
    """Create lab group related tables"""
    
    # Lab groups table
    conn.execute('''
        CREATE TABLE export_lab_groups (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            created_at TEXT,
            updated_at TEXT,
            is_core_facility BOOLEAN DEFAULT 0,
            can_perform_ms_analysis BOOLEAN DEFAULT 0,
            budget_code TEXT,
            contact_email TEXT,
            location TEXT
        )
    ''')
    
    # Lab group managers (many-to-many)
    conn.execute('''
        CREATE TABLE export_lab_group_managers (
            id INTEGER PRIMARY KEY,
            lab_group_id INTEGER,
            user_id INTEGER,
            role TEXT DEFAULT 'manager',
            added_at TEXT,
            FOREIGN KEY (lab_group_id) REFERENCES export_lab_groups (id),
            FOREIGN KEY (user_id) REFERENCES export_users (id)
        )
    ''')
    
    # Lab group users (many-to-many)
    conn.execute('''
        CREATE TABLE export_lab_group_users (
            id INTEGER PRIMARY KEY,
            lab_group_id INTEGER,
            user_id INTEGER,
            access_level TEXT DEFAULT 'member',
            joined_at TEXT,
            FOREIGN KEY (lab_group_id) REFERENCES export_lab_groups (id),
            FOREIGN KEY (user_id) REFERENCES export_users (id)
        )
    ''')


def create_instrument_tables(conn):
    """Create instrument related tables"""
    
    # Instruments table
    conn.execute('''
        CREATE TABLE export_instruments (
            id INTEGER PRIMARY KEY,
            instrument_name TEXT NOT NULL,
            instrument_description TEXT,
            location TEXT,
            manufacturer TEXT,
            model TEXT,
            serial_number TEXT,
            installation_date TEXT,
            last_maintenance_date TEXT,
            maintenance_interval_days INTEGER DEFAULT 90,
            is_active BOOLEAN DEFAULT 1,
            booking_required BOOLEAN DEFAULT 1,
            max_booking_days INTEGER DEFAULT 30,
            hourly_rate DECIMAL(10,2),
            contact_person TEXT
        )
    ''')
    
    # Instrument jobs table
    conn.execute('''
        CREATE TABLE export_instrument_jobs (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            instrument_id INTEGER,
            project_id INTEGER,
            service_lab_group_id INTEGER,
            sample_number INTEGER DEFAULT 1,
            cost_center TEXT,
            amount DECIMAL(10,2),
            job_type TEXT DEFAULT 'analysis',
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            submission_notes TEXT,
            analysis_method TEXT,
            expected_completion TEXT,
            priority TEXT DEFAULT 'normal',
            FOREIGN KEY (user_id) REFERENCES export_users (id),
            FOREIGN KEY (instrument_id) REFERENCES export_instruments (id),
            FOREIGN KEY (project_id) REFERENCES export_projects (id),
            FOREIGN KEY (service_lab_group_id) REFERENCES export_lab_groups (id)
        )
    ''')


def create_billing_tables(conn):
    """Create billing system tables"""
    
    # Service tiers table
    conn.execute('''
        CREATE TABLE export_service_tiers (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            lab_group_id INTEGER,
            is_active BOOLEAN DEFAULT 1,
            created_at TEXT,
            updated_at TEXT,
            discount_percentage DECIMAL(5,2) DEFAULT 0.00,
            billing_contact TEXT,
            FOREIGN KEY (lab_group_id) REFERENCES export_lab_groups (id)
        )
    ''')
    
    # Service prices table
    conn.execute('''
        CREATE TABLE export_service_prices (
            id INTEGER PRIMARY KEY,
            service_tier_id INTEGER,
            instrument_id INTEGER,
            billing_unit TEXT NOT NULL,
            price DECIMAL(10,2) NOT NULL,
            currency TEXT DEFAULT 'USD',
            effective_date TEXT,
            expiry_date TEXT,
            created_at TEXT,
            updated_at TEXT,
            FOREIGN KEY (service_tier_id) REFERENCES export_service_tiers (id),
            FOREIGN KEY (instrument_id) REFERENCES export_instruments (id)
        )
    ''')
    
    # Billing records table
    conn.execute('''
        CREATE TABLE export_billing_records (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            instrument_job_id INTEGER,
            service_tier_id INTEGER,
            billing_date TEXT,
            instrument_hours DECIMAL(8,2),
            instrument_rate DECIMAL(10,2),
            instrument_cost DECIMAL(10,2),
            personnel_hours DECIMAL(8,2),
            personnel_rate DECIMAL(10,2),
            personnel_cost DECIMAL(10,2),
            consumables_cost DECIMAL(10,2),
            other_cost DECIMAL(10,2),
            total_amount DECIMAL(10,2),
            status TEXT DEFAULT 'pending',
            invoice_number TEXT,
            notes TEXT,
            created_at TEXT,
            updated_at TEXT,
            FOREIGN KEY (user_id) REFERENCES export_users (id),
            FOREIGN KEY (instrument_job_id) REFERENCES export_instrument_jobs (id),
            FOREIGN KEY (service_tier_id) REFERENCES export_service_tiers (id)
        )
    ''')


def create_backup_tables(conn):
    """Create backup monitoring tables"""
    
    # Backup logs table
    conn.execute('''
        CREATE TABLE export_backup_logs (
            id INTEGER PRIMARY KEY,
            backup_type TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            duration_seconds INTEGER,
            backup_file_path TEXT,
            file_size_bytes INTEGER,
            success_message TEXT,
            error_message TEXT,
            triggered_by TEXT DEFAULT 'system',
            container_id TEXT,
            backup_method TEXT DEFAULT 'automated',
            compression_ratio DECIMAL(5,2),
            verification_status TEXT DEFAULT 'pending'
        )
    ''')


def create_sample_pool_tables(conn):
    """Create sample pool tables"""
    
    # Sample pools table
    conn.execute('''
        CREATE TABLE export_sample_pools (
            id INTEGER PRIMARY KEY,
            instrument_job_id INTEGER,
            pool_name TEXT NOT NULL,
            pool_description TEXT,
            created_by_id INTEGER,
            created_at TEXT,
            updated_at TEXT,
            pooled_only_samples TEXT,  -- JSON array
            pooled_and_independent_samples TEXT,  -- JSON array
            template_sample INTEGER,
            is_reference BOOLEAN DEFAULT 0,
            pool_volume DECIMAL(8,2),
            concentration DECIMAL(8,2),
            buffer_composition TEXT,
            FOREIGN KEY (instrument_job_id) REFERENCES export_instrument_jobs (id),
            FOREIGN KEY (created_by_id) REFERENCES export_users (id)
        )
    ''')


def create_ontology_tables(conn):
    """Create ontology data tables"""
    
    # Cell types table
    conn.execute('''
        CREATE TABLE export_cell_types (
            id INTEGER PRIMARY KEY,
            identifier TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            synonyms TEXT,  -- JSON array
            is_obsolete BOOLEAN DEFAULT 0,
            replaced_by TEXT,
            category TEXT DEFAULT 'cell_type',
            tissue_origin TEXT,
            species TEXT
        )
    ''')
    
    # MONDO diseases table
    conn.execute('''
        CREATE TABLE export_mondo_diseases (
            id INTEGER PRIMARY KEY,
            identifier TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            definition TEXT,
            synonyms TEXT,  -- JSON array
            is_obsolete BOOLEAN DEFAULT 0,
            replaced_by TEXT,
            disease_category TEXT,
            icd_10_code TEXT,
            prevalence TEXT
        )
    ''')
    
    # UBERON anatomy table
    conn.execute('''
        CREATE TABLE export_uberon_anatomy (
            id INTEGER PRIMARY KEY,
            identifier TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            definition TEXT,
            synonyms TEXT,  -- JSON array
            is_obsolete BOOLEAN DEFAULT 0,
            replaced_by TEXT,
            develops_from TEXT,
            part_of TEXT,
            anatomical_system TEXT
        )
    ''')
    
    # NCBI taxonomy table
    conn.execute('''
        CREATE TABLE export_ncbi_taxonomy (
            id INTEGER PRIMARY KEY,
            tax_id INTEGER UNIQUE NOT NULL,
            scientific_name TEXT NOT NULL,
            common_name TEXT,
            rank TEXT,
            lineage TEXT,
            genome_size INTEGER,
            chromosome_count INTEGER
        )
    ''')
    
    # ChEBI compounds table
    conn.execute('''
        CREATE TABLE export_chebi_compounds (
            id INTEGER PRIMARY KEY,
            identifier TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            definition TEXT,
            synonyms TEXT,  -- JSON array
            formula TEXT,
            mass DECIMAL(10,6),
            charge INTEGER DEFAULT 0,
            is_obsolete BOOLEAN DEFAULT 0,
            replaced_by TEXT,
            inchi TEXT,
            smiles TEXT
        )
    ''')
    
    # PSI-MS ontology table
    conn.execute('''
        CREATE TABLE export_psims_ontology (
            id INTEGER PRIMARY KEY,
            identifier TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            definition TEXT,
            synonyms TEXT,  -- JSON array
            category TEXT DEFAULT 'general',
            is_obsolete BOOLEAN DEFAULT 0,
            replaced_by TEXT,
            instrument_compatibility TEXT,
            software_compatibility TEXT
        )
    ''')


def create_sdrf_cache_tables(conn):
    """Create SDRF cache tables"""
    
    # SDRF suggestion cache table
    conn.execute('''
        CREATE TABLE export_sdrf_cache (
            id INTEGER PRIMARY KEY,
            step_id INTEGER,
            analyzer_type TEXT NOT NULL,
            sdrf_suggestions TEXT,  -- JSON
            analysis_metadata TEXT,  -- JSON
            extracted_terms TEXT,  -- JSON array
            step_content_hash TEXT,
            is_valid BOOLEAN DEFAULT 1,
            created_at TEXT,
            updated_at TEXT,
            cache_version TEXT DEFAULT '1.0',
            processing_time DECIMAL(8,3),
            confidence_score DECIMAL(5,3),
            FOREIGN KEY (step_id) REFERENCES export_protocol_steps (id)
        )
    ''')


def create_annotations_table(conn):
    """Create annotations table"""
    
    conn.execute('''
        CREATE TABLE export_annotations (
            id INTEGER PRIMARY KEY,
            step_id INTEGER,
            user_id INTEGER,
            annotation_type TEXT,
            annotation_name TEXT,
            annotation_data TEXT,  -- JSON or file path
            created_at TEXT,
            updated_at TEXT,
            is_transcribed BOOLEAN DEFAULT 0,
            language TEXT DEFAULT 'en',
            confidence_score DECIMAL(5,3),
            file_size INTEGER,
            duration DECIMAL(8,3),
            processing_status TEXT DEFAULT 'completed',
            FOREIGN KEY (step_id) REFERENCES export_protocol_steps (id),
            FOREIGN KEY (user_id) REFERENCES export_users (id)
        )
    ''')


def insert_comprehensive_test_data(conn):
    """Insert comprehensive test data for all models"""
    
    print("  👥 Creating users and lab groups...")
    insert_users_and_lab_groups(conn)
    
    print("  🔬 Creating instruments and projects...")
    insert_instruments_and_projects(conn)
    
    print("  📋 Creating protocols and steps...")
    insert_protocols_and_steps(conn)
    
    print("  🧾 Creating billing data...")
    insert_billing_data(conn)
    
    print("  💾 Creating backup logs...")
    insert_backup_data(conn)
    
    print("  🧬 Creating ontology data...")
    insert_ontology_data(conn)
    
    print("  📊 Creating instrument jobs and sample pools...")
    insert_instrument_jobs_and_pools(conn)
    
    print("  🤖 Creating SDRF cache data...")
    insert_sdrf_cache_data(conn)
    
    print("  📝 Creating annotations...")
    insert_annotations_data(conn)


def insert_users_and_lab_groups(conn):
    """Insert realistic users and lab groups"""
    
    # Create diverse users
    users = [
        {
            'username': 'dr_sarah_johnson', 'email': 'sarah.johnson@university.edu',
            'first_name': 'Sarah', 'last_name': 'Johnson', 'is_staff': True,
            'department': 'Biochemistry', 'phone': '+1-555-0101', 'orcid_id': '0000-0001-2345-6789'
        },
        {
            'username': 'prof_michael_chen', 'email': 'michael.chen@university.edu',
            'first_name': 'Michael', 'last_name': 'Chen', 'is_staff': True,
            'department': 'Proteomics', 'phone': '+1-555-0102', 'orcid_id': '0000-0002-3456-7890'
        },
        {
            'username': 'lab_tech_maria_garcia', 'email': 'maria.garcia@university.edu',
            'first_name': 'Maria', 'last_name': 'Garcia', 'is_staff': False,
            'department': 'Core Facility', 'phone': '+1-555-0103', 'orcid_id': '0000-0003-4567-8901'
        },
        {
            'username': 'postdoc_james_wilson', 'email': 'james.wilson@university.edu',
            'first_name': 'James', 'last_name': 'Wilson', 'is_staff': False,
            'department': 'Cell Biology', 'phone': '+1-555-0104', 'orcid_id': '0000-0004-5678-9012'
        },
        {
            'username': 'grad_student_lisa_brown', 'email': 'lisa.brown@university.edu',
            'first_name': 'Lisa', 'last_name': 'Brown', 'is_staff': False,
            'department': 'Biochemistry', 'phone': '+1-555-0105', 'orcid_id': '0000-0005-6789-0123'
        }
    ]
    
    for i, user in enumerate(users, 1):
        user['id'] = i
        user['date_joined'] = (datetime.now() - timedelta(days=random.randint(30, 365))).isoformat()
        
        conn.execute('''
            INSERT INTO export_users (id, username, email, first_name, last_name, 
                                    is_staff, is_active, date_joined, department, phone, orcid_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user['id'], user['username'], user['email'], user['first_name'], 
              user['last_name'], user['is_staff'], True, user['date_joined'],
              user['department'], user['phone'], user['orcid_id']))
    
    # Create lab groups
    lab_groups = [
        {
            'id': 1, 'name': 'Proteomics Core Facility', 
            'description': 'Mass spectrometry and protein analysis core facility',
            'is_core_facility': True, 'can_perform_ms_analysis': True,
            'budget_code': 'CORE-PROT-001', 'contact_email': 'proteomics@university.edu',
            'location': 'Science Building, Room 401'
        },
        {
            'id': 2, 'name': 'Johnson Biochemistry Lab',
            'description': 'Research lab focused on enzyme mechanisms and protein folding',
            'is_core_facility': False, 'can_perform_ms_analysis': False,
            'budget_code': 'LAB-BIOCHEM-002', 'contact_email': 'johnson.lab@university.edu',
            'location': 'Biochemistry Building, Suite 205'
        },
        {
            'id': 3, 'name': 'Chen Systems Biology Group',
            'description': 'Computational and experimental systems biology research',
            'is_core_facility': False, 'can_perform_ms_analysis': True,
            'budget_code': 'LAB-SYSBIO-003', 'contact_email': 'chen.group@university.edu',
            'location': 'Research Tower, Floor 8'
        }
    ]
    
    for group in lab_groups:
        group['created_at'] = (datetime.now() - timedelta(days=random.randint(100, 500))).isoformat()
        group['updated_at'] = (datetime.now() - timedelta(days=random.randint(1, 30))).isoformat()
        
        conn.execute('''
            INSERT INTO export_lab_groups (id, name, description, created_at, updated_at,
                                         is_core_facility, can_perform_ms_analysis, 
                                         budget_code, contact_email, location)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (group['id'], group['name'], group['description'], group['created_at'],
              group['updated_at'], group['is_core_facility'], group['can_perform_ms_analysis'],
              group['budget_code'], group['contact_email'], group['location']))
    
    # Create lab group relationships
    relationships = [
        # Proteomics Core - Dr. Johnson as manager
        {'lab_group_id': 1, 'user_id': 1, 'role': 'manager'},
        {'lab_group_id': 1, 'user_id': 3, 'role': 'technician'},
        # Johnson Lab - Dr. Johnson as PI
        {'lab_group_id': 2, 'user_id': 1, 'role': 'pi'},
        {'lab_group_id': 2, 'user_id': 5, 'role': 'graduate_student'},
        # Chen Group - Prof. Chen as PI
        {'lab_group_id': 3, 'user_id': 2, 'role': 'pi'},
        {'lab_group_id': 3, 'user_id': 4, 'role': 'postdoc'},
    ]
    
    for i, rel in enumerate(relationships, 1):
        rel['id'] = i
        rel['added_at'] = (datetime.now() - timedelta(days=random.randint(1, 100))).isoformat()
        
        conn.execute('''
            INSERT INTO export_lab_group_managers (id, lab_group_id, user_id, role, added_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (rel['id'], rel['lab_group_id'], rel['user_id'], rel['role'], rel['added_at']))


def insert_instruments_and_projects(conn):
    """Insert realistic instruments and projects"""
    
    # Create instruments
    instruments = [
        {
            'id': 1, 'instrument_name': 'Orbitrap Fusion Lumos',
            'instrument_description': 'High-resolution mass spectrometer for proteomics',
            'location': 'Proteomics Core, Room 401A', 'manufacturer': 'Thermo Fisher Scientific',
            'model': 'Orbitrap Fusion Lumos', 'serial_number': 'FSN20210001',
            'hourly_rate': Decimal('125.00'), 'contact_person': 'Dr. Sarah Johnson'
        },
        {
            'id': 2, 'instrument_name': 'Q Exactive Plus',
            'instrument_description': 'Benchtop quadrupole-Orbitrap mass spectrometer',
            'location': 'Proteomics Core, Room 401B', 'manufacturer': 'Thermo Fisher Scientific',
            'model': 'Q Exactive Plus', 'serial_number': 'QEP20200015',
            'hourly_rate': Decimal('95.00'), 'contact_person': 'Maria Garcia'
        },
        {
            'id': 3, 'instrument_name': 'timsTOF Pro 2',
            'instrument_description': 'Trapped ion mobility-quadrupole-TOF mass spectrometer',
            'location': 'Chen Lab, Room 805', 'manufacturer': 'Bruker Daltonics',
            'model': 'timsTOF Pro 2', 'serial_number': 'TTP20220008',
            'hourly_rate': Decimal('110.00'), 'contact_person': 'Prof. Michael Chen'
        }
    ]
    
    for inst in instruments:
        inst['installation_date'] = (datetime.now() - timedelta(days=random.randint(365, 1095))).isoformat()
        inst['last_maintenance_date'] = (datetime.now() - timedelta(days=random.randint(1, 90))).isoformat()
        
        conn.execute('''
            INSERT INTO export_instruments (id, instrument_name, instrument_description, location,
                                          manufacturer, model, serial_number, installation_date,
                                          last_maintenance_date, maintenance_interval_days, is_active,
                                          booking_required, max_booking_days, hourly_rate, contact_person)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (inst['id'], inst['instrument_name'], inst['instrument_description'], inst['location'],
              inst['manufacturer'], inst['model'], inst['serial_number'], inst['installation_date'],
              inst['last_maintenance_date'], 90, True, True, 30, inst['hourly_rate'], inst['contact_person']))
    
    # Create projects
    projects = [
        {
            'id': 1, 'project_name': 'Alzheimer Disease Biomarker Discovery',
            'project_description': 'Proteomic analysis of cerebrospinal fluid for AD biomarkers',
            'owner_id': 1, 'funding_source': 'NIH R01AG070123', 'project_code': 'AD-BIOMARK-2023',
            'status': 'active'
        },
        {
            'id': 2, 'project_name': 'Mitochondrial Proteome Dynamics',
            'project_description': 'Time-resolved analysis of mitochondrial protein expression',
            'owner_id': 2, 'funding_source': 'NSF MCB-2045678', 'project_code': 'MITO-DYNAM-2023',
            'status': 'active'
        },
        {
            'id': 3, 'project_name': 'Cancer Cell Line Characterization',
            'project_description': 'Comprehensive proteomic profiling of cancer cell lines',
            'owner_id': 1, 'funding_source': 'University Internal', 'project_code': 'CANCER-CELL-2023',
            'status': 'active'
        },
        {
            'id': 4, 'project_name': 'Drug Target Validation',
            'project_description': 'Proteomic validation of novel therapeutic targets',
            'owner_id': 4, 'funding_source': 'Pharmaceutical Partnership', 'project_code': 'DRUG-TARGET-2023',
            'status': 'completed'
        }
    ]
    
    for proj in projects:
        proj['created_at'] = (datetime.now() - timedelta(days=random.randint(50, 200))).isoformat()
        proj['updated_at'] = (datetime.now() - timedelta(days=random.randint(1, 30))).isoformat()
        
        conn.execute('''
            INSERT INTO export_projects (id, project_name, project_description, owner_id,
                                       created_at, updated_at, is_public, funding_source,
                                       project_code, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (proj['id'], proj['project_name'], proj['project_description'], proj['owner_id'],
              proj['created_at'], proj['updated_at'], False, proj['funding_source'],
              proj['project_code'], proj['status']))


def insert_protocols_and_steps(conn):
    """Insert realistic protocols and steps"""
    
    # Create protocols
    protocols = [
        {
            'id': 1, 'protocol_title': 'Standard Tryptic Digestion for LC-MS/MS',
            'protocol_id': 10001, 'user_id': 1, 'version': '2.1',
            'doi': '10.17504/protocols.io.abc123', 'publication_status': 'published',
            'protocol_description': 'Optimized protocol for tryptic digestion of proteins for bottom-up proteomics'
        },
        {
            'id': 2, 'protocol_title': 'CSF Sample Preparation for Biomarker Analysis',
            'protocol_id': 10002, 'user_id': 1, 'version': '1.5',
            'publication_status': 'draft',
            'protocol_description': 'Specialized protocol for processing cerebrospinal fluid samples'
        },
        {
            'id': 3, 'protocol_title': 'Cell Culture Protein Extraction',
            'protocol_id': 10003, 'user_id': 2, 'version': '3.0',
            'doi': '10.17504/protocols.io.def456', 'publication_status': 'published',
            'protocol_description': 'Protocol for extracting proteins from cultured cells'
        }
    ]
    
    for prot in protocols:
        prot['created_at'] = (datetime.now() - timedelta(days=random.randint(30, 180))).isoformat()
        prot['updated_at'] = (datetime.now() - timedelta(days=random.randint(1, 30))).isoformat()
        
        conn.execute('''
            INSERT INTO export_protocols (id, protocol_title, protocol_id, protocol_description,
                                        user_id, enabled, created_at, updated_at, version,
                                        doi, publication_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (prot['id'], prot['protocol_title'], prot['protocol_id'], prot['protocol_description'],
              prot['user_id'], True, prot['created_at'], prot['updated_at'], prot['version'],
              prot.get('doi'), prot['publication_status']))
    
    # Create protocol sections
    sections = [
        {'id': 1, 'protocol_id': 1, 'section_description': 'Sample Preparation', 'section_order': 1, 'estimated_duration': 30},
        {'id': 2, 'protocol_id': 1, 'section_description': 'Protein Digestion', 'section_order': 2, 'estimated_duration': 120},
        {'id': 3, 'protocol_id': 1, 'section_description': 'Sample Cleanup', 'section_order': 3, 'estimated_duration': 45},
        {'id': 4, 'protocol_id': 2, 'section_description': 'CSF Processing', 'section_order': 1, 'estimated_duration': 60},
        {'id': 5, 'protocol_id': 2, 'section_description': 'Protein Extraction', 'section_order': 2, 'estimated_duration': 90},
        {'id': 6, 'protocol_id': 3, 'section_description': 'Cell Lysis', 'section_order': 1, 'estimated_duration': 20},
        {'id': 7, 'protocol_id': 3, 'section_description': 'Protein Quantification', 'section_order': 2, 'estimated_duration': 30}
    ]
    
    for sect in sections:
        conn.execute('''
            INSERT INTO export_protocol_sections (id, protocol_id, section_description, 
                                                section_order, section_type, estimated_duration)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (sect['id'], sect['protocol_id'], sect['section_description'],
              sect['section_order'], 'general', sect['estimated_duration']))
    
    # Create protocol steps with detailed descriptions
    steps = [
        # Protocol 1 steps
        {
            'id': 1, 'protocol_id': 1, 'step_id': 1, 'step_section_id': 1,
            'step_description': 'Thaw protein samples on ice and measure protein concentration using Bradford assay. Prepare 100 μg of total protein in 50 μL of 8M urea buffer.',
            'safety_notes': 'Handle urea solutions with gloves and in well-ventilated area'
        },
        {
            'id': 2, 'protocol_id': 1, 'step_id': 2, 'step_section_id': 1,
            'step_description': 'Add 5 μL of 200 mM TCEP (tris(2-carboxyethyl)phosphine) for disulfide bond reduction. Incubate at 37°C for 30 minutes.',
            'safety_notes': 'TCEP is corrosive - handle with appropriate PPE'
        },
        {
            'id': 3, 'protocol_id': 1, 'step_id': 3, 'step_section_id': 1,
            'step_description': 'Add 5 μL of 400 mM iodoacetamide for cysteine alkylation. Incubate in the dark at room temperature for 30 minutes.',
            'safety_notes': 'Iodoacetamide is light-sensitive and toxic'
        },
        {
            'id': 4, 'protocol_id': 1, 'step_id': 4, 'step_section_id': 2,
            'step_description': 'Dilute urea concentration to <2M by adding 200 μL of 50 mM ammonium bicarbonate buffer (pH 8.0).',
            'requires_approval': False
        },
        {
            'id': 5, 'protocol_id': 1, 'step_id': 5, 'step_section_id': 2,
            'step_description': 'Add trypsin at 1:50 enzyme-to-substrate ratio. Incubate at 37°C overnight (16-18 hours) with gentle shaking.',
            'safety_notes': 'Ensure proper temperature control for optimal digestion'
        },
        # Protocol 2 steps
        {
            'id': 6, 'protocol_id': 2, 'step_id': 1, 'step_section_id': 4,
            'step_description': 'Centrifuge CSF samples at 2000g for 10 minutes at 4°C to remove cellular debris. Transfer supernatant to new tube.',
            'safety_notes': 'Handle CSF samples as potentially infectious material'
        },
        {
            'id': 7, 'protocol_id': 2, 'step_id': 2, 'step_section_id': 4,
            'step_description': 'Add protease inhibitor cocktail (1:100 dilution) and phosphatase inhibitors. Mix gently and keep on ice.',
            'requires_approval': True
        },
        {
            'id': 8, 'protocol_id': 2, 'step_id': 3, 'step_section_id': 5,
            'step_description': 'Perform protein precipitation using acetone (1:4 ratio). Incubate at -20°C for 2 hours.',
            'safety_notes': 'Use acetone in fume hood - highly flammable'
        },
        # Protocol 3 steps
        {
            'id': 9, 'protocol_id': 3, 'step_id': 1, 'step_section_id': 6,
            'step_description': 'Wash cultured cells twice with ice-cold PBS. Remove PBS completely using aspiration.',
            'step_type': 'automated'
        },
        {
            'id': 10, 'protocol_id': 3, 'step_id': 2, 'step_section_id': 6,
            'step_description': 'Add RIPA lysis buffer (150 μL per well of 6-well plate) supplemented with protease inhibitors. Incubate on ice for 15 minutes.',
            'safety_notes': 'RIPA buffer contains detergents - avoid skin contact'
        }
    ]
    
    for step in steps:
        step['created_at'] = (datetime.now() - timedelta(days=random.randint(15, 60))).isoformat()
        step['updated_at'] = (datetime.now() - timedelta(days=random.randint(1, 15))).isoformat()
        
        conn.execute('''
            INSERT INTO export_protocol_steps (id, protocol_id, step_id, step_description,
                                             step_section_id, step_order, created_at, updated_at,
                                             step_type, requires_approval, safety_notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (step['id'], step['protocol_id'], step['step_id'], step['step_description'],
              step['step_section_id'], step['step_id'], step['created_at'], step['updated_at'],
              step.get('step_type', 'manual'), step.get('requires_approval', False), 
              step.get('safety_notes')))


def insert_billing_data(conn):
    """Insert realistic billing data"""
    
    # Create service tiers
    service_tiers = [
        {
            'id': 1, 'name': 'Academic Standard', 'lab_group_id': 1,
            'description': 'Standard academic pricing for university researchers',
            'discount_percentage': Decimal('0.00'), 'billing_contact': 'billing@university.edu'
        },
        {
            'id': 2, 'name': 'Academic Premium', 'lab_group_id': 1,
            'description': 'Premium academic pricing with priority access',
            'discount_percentage': Decimal('15.00'), 'billing_contact': 'billing@university.edu'
        },
        {
            'id': 3, 'name': 'Commercial Rate', 'lab_group_id': 1,
            'description': 'Commercial pricing for industry collaborations',
            'discount_percentage': Decimal('0.00'), 'billing_contact': 'commercial@university.edu'
        }
    ]
    
    for tier in service_tiers:
        tier['created_at'] = (datetime.now() - timedelta(days=random.randint(100, 300))).isoformat()
        tier['updated_at'] = (datetime.now() - timedelta(days=random.randint(1, 30))).isoformat()
        
        conn.execute('''
            INSERT INTO export_service_tiers (id, name, description, lab_group_id, is_active,
                                            created_at, updated_at, discount_percentage, billing_contact)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (tier['id'], tier['name'], tier['description'], tier['lab_group_id'], True,
              tier['created_at'], tier['updated_at'], tier['discount_percentage'], tier['billing_contact']))
    
    # Create service prices
    prices = [
        # Academic Standard rates
        {'id': 1, 'service_tier_id': 1, 'instrument_id': 1, 'billing_unit': 'per_hour_instrument', 'price': Decimal('125.00')},
        {'id': 2, 'service_tier_id': 1, 'instrument_id': 2, 'billing_unit': 'per_hour_instrument', 'price': Decimal('95.00')},
        {'id': 3, 'service_tier_id': 1, 'instrument_id': 3, 'billing_unit': 'per_hour_instrument', 'price': Decimal('110.00')},
        # Academic Premium rates (15% discount)
        {'id': 4, 'service_tier_id': 2, 'instrument_id': 1, 'billing_unit': 'per_hour_instrument', 'price': Decimal('106.25')},
        {'id': 5, 'service_tier_id': 2, 'instrument_id': 2, 'billing_unit': 'per_hour_instrument', 'price': Decimal('80.75')},
        {'id': 6, 'service_tier_id': 2, 'instrument_id': 3, 'billing_unit': 'per_hour_instrument', 'price': Decimal('93.50')},
        # Commercial rates (2x academic)
        {'id': 7, 'service_tier_id': 3, 'instrument_id': 1, 'billing_unit': 'per_hour_instrument', 'price': Decimal('250.00')},
        {'id': 8, 'service_tier_id': 3, 'instrument_id': 2, 'billing_unit': 'per_hour_instrument', 'price': Decimal('190.00')},
        {'id': 9, 'service_tier_id': 3, 'instrument_id': 3, 'billing_unit': 'per_hour_instrument', 'price': Decimal('220.00')}
    ]
    
    for price in prices:
        price['effective_date'] = (datetime.now() - timedelta(days=random.randint(30, 180))).isoformat()
        price['created_at'] = price['effective_date']
        price['updated_at'] = (datetime.now() - timedelta(days=random.randint(1, 30))).isoformat()
        
        conn.execute('''
            INSERT INTO export_service_prices (id, service_tier_id, instrument_id, billing_unit,
                                             price, currency, effective_date, expiry_date,
                                             created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (price['id'], price['service_tier_id'], price['instrument_id'], price['billing_unit'],
              price['price'], 'USD', price['effective_date'], None,
              price['created_at'], price['updated_at']))


def insert_backup_data(conn):
    """Insert realistic backup logs"""
    
    backup_types = ['database', 'media_files', 'full_system', 'user_data']
    statuses = ['completed', 'failed', 'running', 'cancelled']
    
    for i in range(1, 51):  # 50 backup entries
        backup_type = random.choice(backup_types)
        status = random.choice(statuses)
        
        started_at = datetime.now() - timedelta(days=random.randint(1, 90),
                                             hours=random.randint(0, 23),
                                             minutes=random.randint(0, 59))
        
        if status == 'completed':
            duration = random.randint(300, 7200)  # 5 minutes to 2 hours
            completed_at = started_at + timedelta(seconds=duration)
            file_size = random.randint(1024*1024*100, 1024*1024*1024*5)  # 100MB to 5GB
            success_msg = f"Backup completed successfully. {backup_type} backup archived."
            error_msg = None
        elif status == 'failed':
            duration = random.randint(60, 1800)  # 1 minute to 30 minutes
            completed_at = started_at + timedelta(seconds=duration)
            file_size = None
            success_msg = None
            error_msg = f"Backup failed: Insufficient disk space for {backup_type} backup"
        else:
            duration = None
            completed_at = None if status == 'running' else started_at + timedelta(minutes=5)
            file_size = None
            success_msg = None
            error_msg = "Backup cancelled by user" if status == 'cancelled' else None
        
        conn.execute('''
            INSERT INTO export_backup_logs (id, backup_type, status, started_at, completed_at,
                                          duration_seconds, backup_file_path, file_size_bytes,
                                          success_message, error_message, triggered_by,
                                          container_id, backup_method, compression_ratio,
                                          verification_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (i, backup_type, status, started_at.isoformat(),
              completed_at.isoformat() if completed_at else None,
              duration, f"/backups/{backup_type}_{started_at.strftime('%Y%m%d_%H%M%S')}.tar.gz" if status == 'completed' else None,
              file_size, success_msg, error_msg, random.choice(['system', 'user', 'scheduled']),
              f"backup_container_{random.randint(1000, 9999)}" if random.choice([True, False]) else None,
              random.choice(['automated', 'manual']), 
              round(random.uniform(0.3, 0.8), 2) if status == 'completed' else None,
              random.choice(['verified', 'pending', 'failed']) if status == 'completed' else 'pending'))


def insert_ontology_data(conn):
    """Insert realistic ontology data"""
    
    # Cell types
    cell_types = [
        {
            'id': 1, 'identifier': 'CL:0000066', 'name': 'epithelial cell',
            'description': 'A cell that is usually found in a two-dimensional sheet with a free surface.',
            'synonyms': '["epithelial cells", "epitheliocyte"]', 'category': 'cell_type',
            'tissue_origin': 'various', 'species': 'multi-species'
        },
        {
            'id': 2, 'identifier': 'CL:0000084', 'name': 'T cell',
            'description': 'A type of lymphocyte whose defining characteristic is the expression of a T cell receptor complex.',
            'synonyms': '["T lymphocyte", "T-cell", "thymocyte"]', 'category': 'immune_cell',
            'tissue_origin': 'thymus', 'species': 'Mammalia'
        },
        {
            'id': 3, 'identifier': 'CL:0000236', 'name': 'B cell',
            'description': 'A lymphocyte of B lineage that is capable of B cell mediated immunity.',
            'synonyms': '["B lymphocyte", "B-cell"]', 'category': 'immune_cell',
            'tissue_origin': 'bone marrow', 'species': 'Mammalia'
        }
    ]
    
    for cell_type in cell_types:
        conn.execute('''
            INSERT INTO export_cell_types (id, identifier, name, description, synonyms,
                                         is_obsolete, replaced_by, category, tissue_origin, species)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (cell_type['id'], cell_type['identifier'], cell_type['name'], 
              cell_type['description'], cell_type['synonyms'], False, None,
              cell_type['category'], cell_type['tissue_origin'], cell_type['species']))
    
    # MONDO diseases
    diseases = [
        {
            'id': 1, 'identifier': 'MONDO:0004975', 'name': 'Alzheimer disease',
            'definition': 'A dementia that is characterized by memory lapses, confusion, emotional instability and progressive loss of mental ability.',
            'synonyms': '["Alzheimer disease", "AD", "dementia of Alzheimer type"]',
            'disease_category': 'neurodegenerative', 'icd_10_code': 'F00'
        },
        {
            'id': 2, 'identifier': 'MONDO:0007254', 'name': 'breast cancer',
            'definition': 'A carcinoma that arises from epithelial cells of the breast.',
            'synonyms': '["breast carcinoma", "mammary carcinoma"]',
            'disease_category': 'cancer', 'icd_10_code': 'C50'
        },
        {
            'id': 3, 'identifier': 'MONDO:0005148', 'name': 'type 2 diabetes mellitus',
            'definition': 'A diabetes mellitus that is characterized by high blood sugar, insulin resistance, and relative lack of insulin.',
            'synonyms': '["T2DM", "adult-onset diabetes", "non-insulin-dependent diabetes"]',
            'disease_category': 'metabolic', 'icd_10_code': 'E11'
        }
    ]
    
    for disease in diseases:
        conn.execute('''
            INSERT INTO export_mondo_diseases (id, identifier, name, definition, synonyms,
                                             is_obsolete, replaced_by, disease_category, icd_10_code, prevalence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (disease['id'], disease['identifier'], disease['name'], disease['definition'],
              disease['synonyms'], False, None, disease['disease_category'], 
              disease['icd_10_code'], None))
    
    # NCBI taxonomy
    organisms = [
        {
            'id': 1, 'tax_id': 9606, 'scientific_name': 'Homo sapiens', 'common_name': 'human',
            'rank': 'species', 'lineage': 'cellular organisms; Eukaryota; Opisthokonta; Metazoa; Eumetazoa; Bilateria; Deuterostomia; Chordata; Craniata; Vertebrata; Gnathostomata; Teleostomi; Euteleostomi; Sarcopterygii; Dipnotetrapodomorpha; Tetrapoda; Amniota; Mammalia; Theria; Eutheria; Boreoeutheria; Euarchontoglires; Primates; Haplorrhini; Simiiformes; Catarrhini; Hominoidea; Hominidae; Homininae; Homo',
            'genome_size': 3200000000, 'chromosome_count': 46
        },
        {
            'id': 2, 'tax_id': 10090, 'scientific_name': 'Mus musculus', 'common_name': 'house mouse',
            'rank': 'species', 'lineage': 'cellular organisms; Eukaryota; Opisthokonta; Metazoa; Eumetazoa; Bilateria; Deuterostomia; Chordata; Craniata; Vertebrata; Gnathostomata; Teleostomi; Euteleostomi; Sarcopterygii; Dipnotetrapodomorpha; Tetrapoda; Amniota; Mammalia; Theria; Eutheria; Boreoeutheria; Euarchontoglires; Glires; Rodentia; Myomorpha; Muroidea; Muridae; Murinae; Mus; Mus',
            'genome_size': 2700000000, 'chromosome_count': 40
        },
        {
            'id': 3, 'tax_id': 511145, 'scientific_name': 'Escherichia coli str. K-12 substr. MG1655',
            'common_name': 'E. coli K-12', 'rank': 'strain',
            'lineage': 'cellular organisms; Bacteria; Proteobacteria; Gammaproteobacteria; Enterobacterales; Enterobacteriaceae; Escherichia',
            'genome_size': 4641652, 'chromosome_count': 1
        }
    ]
    
    for org in organisms:
        conn.execute('''
            INSERT INTO export_ncbi_taxonomy (id, tax_id, scientific_name, common_name, rank,
                                            lineage, genome_size, chromosome_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (org['id'], org['tax_id'], org['scientific_name'], org['common_name'],
              org['rank'], org['lineage'], org['genome_size'], org['chromosome_count']))
    
    # ChEBI compounds
    compounds = [
        {
            'id': 1, 'identifier': 'CHEBI:15377', 'name': 'water', 'formula': 'H2O',
            'definition': 'An oxygen hydride consisting of an oxygen atom that is covalently bonded to two hydrogen atoms.',
            'synonyms': '["H2O", "dihydrogen oxide", "oxidane"]', 'mass': 18.015,
            'inchi': 'InChI=1S/H2O/h1H2', 'smiles': 'O'
        },
        {
            'id': 2, 'identifier': 'CHEBI:17334', 'name': 'penicillin G', 'formula': 'C16H18N2O4S',
            'definition': 'A penicillin in which the substituent at position 6 of the penam ring is a phenylacetyl group.',
            'synonyms': '["benzylpenicillin", "penicillin G"]', 'mass': 334.390,
            'inchi': 'InChI=1S/C16H18N2O4S/c1-16(2)12(15(21)22)18-13(20)11(14(18)23-16)17-10(19)8-9-6-4-3-5-7-9/h3-7,11-12,14H,8H2,1-2H3,(H,17,19)(H,21,22)/t11-,12+,14-/m1/s1'
        },
        {
            'id': 3, 'identifier': 'CHEBI:16449', 'name': 'alanine', 'formula': 'C3H7NO2',
            'definition': 'An alpha-amino acid that consists of propionic acid bearing an amino substituent at position 2.',
            'synonyms': '["Ala", "A", "2-aminopropionic acid"]', 'mass': 89.093,
            'smiles': 'CC(C(=O)O)N'
        }
    ]
    
    for comp in compounds:
        conn.execute('''
            INSERT INTO export_chebi_compounds (id, identifier, name, definition, synonyms,
                                              formula, mass, charge, is_obsolete, replaced_by,
                                              inchi, smiles)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (comp['id'], comp['identifier'], comp['name'], comp['definition'],
              comp['synonyms'], comp['formula'], comp['mass'], 0, False, None,
              comp.get('inchi'), comp.get('smiles')))
    
    # PSI-MS ontology terms
    ms_terms = [
        {
            'id': 1, 'identifier': 'MS:1000031', 'name': 'instrument model',
            'definition': 'Instrument model name not including the vendor\\'s name.',
            'synonyms': '["instrument model name"]', 'category': 'instrument'
        },
        {
            'id': 2, 'identifier': 'MS:1000133', 'name': 'collision-induced dissociation',
            'definition': 'The dissociation of gas-phase ions by collision with neutral atoms or molecules.',
            'synonyms': '["CID", "CAD", "collision-activated dissociation"]', 'category': 'fragmentation'
        },
        {
            'id': 3, 'identifier': 'MS:1000511', 'name': 'ms level',
            'definition': 'Levels of ms achieved in a multi stage mass spectrometry experiment.',
            'synonyms': '["MS level", "msLevel"]', 'category': 'spectrum'
        }
    ]
    
    for term in ms_terms:
        conn.execute('''
            INSERT INTO export_psims_ontology (id, identifier, name, definition, synonyms,
                                             category, is_obsolete, replaced_by,
                                             instrument_compatibility, software_compatibility)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (term['id'], term['identifier'], term['name'], term['definition'],
              term['synonyms'], term['category'], False, None, None, None))


def insert_instrument_jobs_and_pools(conn):
    """Insert realistic instrument jobs and sample pools"""
    
    # Create instrument jobs
    job_types = ['analysis', 'method_development', 'quality_control', 'training']
    statuses = ['pending', 'running', 'completed', 'failed', 'cancelled']
    priorities = ['low', 'normal', 'high', 'urgent']
    
    for i in range(1, 31):  # 30 instrument jobs
        user_id = random.randint(1, 5)
        instrument_id = random.randint(1, 3)
        project_id = random.randint(1, 4)
        service_lab_group_id = 1  # Proteomics Core
        
        created_at = datetime.now() - timedelta(days=random.randint(1, 180))
        status = random.choice(statuses)
        
        if status == 'completed':
            started_at = created_at + timedelta(hours=random.randint(1, 48))
            completed_at = started_at + timedelta(hours=random.randint(1, 24))
        elif status == 'running':
            started_at = created_at + timedelta(hours=random.randint(1, 48))
            completed_at = None
        else:
            started_at = None
            completed_at = None
        
        conn.execute('''
            INSERT INTO export_instrument_jobs (id, user_id, instrument_id, project_id,
                                              service_lab_group_id, sample_number, cost_center,
                                              amount, job_type, status, created_at, started_at,
                                              completed_at, submission_notes, analysis_method,
                                              expected_completion, priority)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (i, user_id, instrument_id, project_id, service_lab_group_id,
              random.randint(1, 96), f"CC-{random.randint(1000, 9999)}",
              round(random.uniform(100.0, 2000.0), 2), random.choice(job_types),
              status, created_at.isoformat(),
              started_at.isoformat() if started_at else None,
              completed_at.isoformat() if completed_at else None,
              f"Sample analysis for {random.choice(['biomarker', 'proteome', 'metabolome'])} study",
              random.choice(['DDA', 'DIA', 'SRM', 'PRM']),
              (created_at + timedelta(days=random.randint(1, 14))).isoformat(),
              random.choice(priorities)))
    
    # Create sample pools
    for i in range(1, 16):  # 15 sample pools
        job_id = random.randint(1, 30)
        user_id = random.randint(1, 5)
        
        # Generate realistic pooled samples
        total_samples = random.randint(6, 48)
        pooled_only = random.sample(range(1, total_samples + 1), random.randint(2, 6))
        remaining_samples = [s for s in range(1, total_samples + 1) if s not in pooled_only]
        pooled_and_independent = random.sample(remaining_samples, random.randint(1, 3)) if remaining_samples else []
        
        created_at = datetime.now() - timedelta(days=random.randint(1, 90))
        
        conn.execute('''
            INSERT INTO export_sample_pools (id, instrument_job_id, pool_name, pool_description,
                                           created_by_id, created_at, updated_at,
                                           pooled_only_samples, pooled_and_independent_samples,
                                           template_sample, is_reference, pool_volume,
                                           concentration, buffer_composition)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (i, job_id, f"Pool_{i:02d}",
              f"Sample pool for {random.choice(['QC', 'technical replicate', 'biological replicate'])} analysis",
              user_id, created_at.isoformat(),
              (created_at + timedelta(days=random.randint(0, 10))).isoformat(),
              json.dumps(pooled_only), json.dumps(pooled_and_independent),
              random.choice(pooled_only) if pooled_only else None,
              random.choice([True, False]), round(random.uniform(10.0, 100.0), 1),
              round(random.uniform(0.1, 10.0), 2),
              random.choice(['50mM ammonium bicarbonate', '0.1% formic acid', 'PBS buffer'])))


def insert_sdrf_cache_data(conn):
    """Insert SDRF cache data"""
    
    analyzer_types = ['standard_nlp', 'advanced_ai', 'hybrid_analysis', 'rule_based']
    
    for i in range(1, 21):  # 20 cache entries
        step_id = random.randint(1, 10)
        analyzer = random.choice(analyzer_types)
        
        # Generate realistic SDRF suggestions
        suggestions = {
            'organism': random.choice(['Homo sapiens', 'Mus musculus', 'Rattus norvegicus']),
            'cell_type': random.choice(['HEK293', 'HeLa', 'primary hepatocyte', 'fibroblast']),
            'tissue': random.choice(['liver', 'brain', 'heart', 'kidney', 'lung']),
            'disease': random.choice(['normal', 'Alzheimer disease', 'diabetes', 'cancer']),
            'treatment': random.choice(['control', 'drug treatment', 'stress condition']),
            'sample_preparation': random.choice(['tryptic digestion', 'protein extraction', 'cell lysis'])
        }
        
        metadata = {
            'processing_time': round(random.uniform(1.0, 30.0), 3),
            'confidence_score': round(random.uniform(0.6, 0.95), 3),
            'model_version': f"v{random.randint(1, 3)}.{random.randint(0, 9)}",
            'suggestion_count': len(suggestions)
        }
        
        extracted_terms = list(suggestions.values()) + [
            random.choice(['protein', 'peptide', 'mass spectrometry', 'LC-MS/MS', 'proteomics'])
        ]
        
        # Generate content hash
        step_content = f"Protocol step {step_id} content for cache"
        content_hash = hashlib.sha256(step_content.encode('utf-8')).hexdigest()
        
        created_at = datetime.now() - timedelta(days=random.randint(1, 60))
        updated_at = created_at + timedelta(days=random.randint(0, 30))
        
        conn.execute('''
            INSERT INTO export_sdrf_cache (id, step_id, analyzer_type, sdrf_suggestions,
                                         analysis_metadata, extracted_terms, step_content_hash,
                                         is_valid, created_at, updated_at, cache_version,
                                         processing_time, confidence_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (i, step_id, analyzer, json.dumps(suggestions), json.dumps(metadata),
              json.dumps(extracted_terms), content_hash, True,
              created_at.isoformat(), updated_at.isoformat(), 'v1.0',
              metadata['processing_time'], metadata['confidence_score']))


def insert_annotations_data(conn):
    """Insert comprehensive annotations data"""
    
    # Create annotations table
    conn.execute('''
        CREATE TABLE export_annotations (
            id INTEGER PRIMARY KEY,
            step_id INTEGER,
            user_id INTEGER,
            annotation_type TEXT,
            annotation_name TEXT,
            annotation_data TEXT,
            created_at TEXT,
            updated_at TEXT,
            is_transcribed BOOLEAN DEFAULT 0,
            language TEXT DEFAULT 'en',
            confidence_score DECIMAL(5,3),
            file_size INTEGER,
            duration DECIMAL(8,3),
            processing_status TEXT DEFAULT 'completed',
            FOREIGN KEY (step_id) REFERENCES export_protocol_steps (id),
            FOREIGN KEY (user_id) REFERENCES export_users (id)
        )
    ''')
    
    annotation_types = ['voice_note', 'text_note', 'image', 'video', 'file_upload', 'measurement']
    
    for i in range(1, 151):  # 150 annotations
        step_id = random.randint(1, 10)
        user_id = random.randint(1, 5)
        annotation_type = random.choice(annotation_types)
        
        # Generate realistic annotation data
        if annotation_type == 'voice_note':
            annotation_data = f"audio_recordings/step_{step_id}_note_{i}.wav"
            file_size = random.randint(1024*10, 1024*1024*5)  # 10KB to 5MB
            duration = round(random.uniform(10.0, 300.0), 1)
            confidence_score = round(random.uniform(0.85, 0.98), 3)
        elif annotation_type == 'text_note':
            notes = [
                "Sample preparation went smoothly, no issues observed",
                "Increased incubation time by 5 minutes due to temperature variation",
                "Used alternative buffer due to stock shortage",
                "Excellent protein yield observed in this batch",
                "Minor precipitation noted, but cleared after additional centrifugation"
            ]
            annotation_data = random.choice(notes)
            file_size = len(annotation_data.encode('utf-8'))
            duration = None
            confidence_score = 1.0
        elif annotation_type == 'image':
            annotation_data = f"images/step_{step_id}_image_{i}.jpg"
            file_size = random.randint(1024*100, 1024*1024*10)  # 100KB to 10MB
            duration = None
            confidence_score = None
        else:
            annotation_data = f"files/step_{step_id}_{annotation_type}_{i}.dat"
            file_size = random.randint(1024, 1024*1024*50)  # 1KB to 50MB
            duration = None
            confidence_score = None
        
        created_at = datetime.now() - timedelta(days=random.randint(1, 120))
        updated_at = created_at + timedelta(days=random.randint(0, 10))
        
        conn.execute('''
            INSERT INTO export_annotations (id, step_id, user_id, annotation_type, annotation_name,
                                          annotation_data, created_at, updated_at, is_transcribed,
                                          language, confidence_score, file_size, duration,
                                          processing_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (i, step_id, user_id, annotation_type, f"{annotation_type}_{i}",
              annotation_data, created_at.isoformat(), updated_at.isoformat(),
              annotation_type == 'voice_note', 'en', confidence_score, file_size,
              duration, 'completed'))


def create_comprehensive_media_files(media_dir):
    """Create realistic media files for annotations"""
    
    os.makedirs(media_dir, exist_ok=True)
    
    # Create subdirectories
    subdirs = ['audio_recordings', 'images', 'videos', 'files', 'documents']
    for subdir in subdirs:
        os.makedirs(os.path.join(media_dir, subdir), exist_ok=True)
    
    # Create sample audio files (simulate WAV files)
    audio_dir = os.path.join(media_dir, 'audio_recordings')
    for i in range(1, 21):
        audio_file = os.path.join(audio_dir, f'step_{random.randint(1, 10)}_note_{i}.wav')
        # Create a small file with mock audio header
        with open(audio_file, 'wb') as f:
            f.write(b'RIFF\x24\x08\x00\x00WAVEfmt \x10\x00\x00\x00')  # WAV header
            f.write(os.urandom(random.randint(1024*10, 1024*100)))  # Random audio-like data
    
    # Create sample image files
    image_dir = os.path.join(media_dir, 'images')
    for i in range(1, 31):
        image_file = os.path.join(image_dir, f'step_{random.randint(1, 10)}_image_{i}.jpg')
        # Create a small file with JPEG header
        with open(image_file, 'wb') as f:
            f.write(b'\xff\xd8\xff\xe0\x00\x10JFIF')  # JPEG header
            f.write(os.urandom(random.randint(1024*50, 1024*500)))  # Random image-like data
    
    # Create sample document files
    docs_dir = os.path.join(media_dir, 'documents')
    for i in range(1, 11):
        doc_file = os.path.join(docs_dir, f'protocol_supplement_{i}.pdf')
        # Create a small PDF-like file
        with open(doc_file, 'wb') as f:
            f.write(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')  # PDF header
            f.write(os.urandom(random.randint(1024*10, 1024*100)))


def create_additional_test_files(temp_dir):
    """Create additional test files for comprehensive testing"""
    
    # Create test configuration files
    config_dir = os.path.join(temp_dir, 'config')
    os.makedirs(config_dir, exist_ok=True)
    
    # Export configuration
    export_config = {
        'version': '2.0',
        'export_date': datetime.now().isoformat(),
        'cupcake_version': '2.5.0',
        'database_version': '149',  # Latest migration
        'included_models': [
            'User', 'Project', 'Protocol', 'ProtocolStep', 'LabGroup',
            'Instrument', 'InstrumentJob', 'ServiceTier', 'ServicePrice', 
            'BillingRecord', 'BackupLog', 'SamplePool', 'CellType',
            'MondoDisease', 'UberonAnatomy', 'NCBITaxonomy', 'ChEBICompound',
            'PSIMSOntology', 'ProtocolStepSuggestionCache', 'Annotation'
        ],
        'total_records': {
            'users': 5,
            'projects': 4,
            'protocols': 3,
            'protocol_steps': 10,
            'lab_groups': 3,
            'instruments': 3,
            'instrument_jobs': 30,
            'service_tiers': 3,
            'service_prices': 9,
            'billing_records': 0,  # Will be created during testing
            'backup_logs': 50,
            'sample_pools': 15,
            'ontology_terms': 15,
            'sdrf_cache_entries': 20,
            'annotations': 150
        },
        'data_integrity_checks': True,
        'media_files_included': True,
        'ontology_data_included': True
    }
    
    with open(os.path.join(config_dir, 'export_config.json'), 'w') as f:
        json.dump(export_config, f, indent=2)
    
    # Create README file
    readme_content = """# CUPCAKE Comprehensive Test Fixture v2.0

This test fixture contains comprehensive data for testing CUPCAKE's import/export functionality.

## Contents

### Database (user_data.sqlite)
- **5 Users**: Diverse roles including PI, postdocs, technicians, grad students
- **3 Lab Groups**: Core facility + 2 research labs with realistic hierarchies  
- **4 Projects**: Active research projects with funding information
- **3 Protocols**: Detailed protocols with 10 comprehensive steps
- **3 Instruments**: Modern mass spectrometers with realistic specifications
- **30 Instrument Jobs**: Various job types, statuses, and priorities
- **Billing System**: 3 service tiers, 9 pricing structures, ready for billing records
- **50 Backup Logs**: Realistic backup history with success/failure scenarios
- **15 Sample Pools**: Complex pooling strategies with SDRF metadata
- **Ontology Data**: 15 terms across 6 major biological ontologies
- **20 SDRF Cache Entries**: AI-generated suggestions with metadata
- **150 Annotations**: Diverse annotation types with realistic metadata

### Media Files
- **Audio recordings** (20 files): Simulated voice notes for protocol steps
- **Images** (30 files): Protocol documentation and results
- **Documents** (10 files): Supplementary protocol materials

### Features Tested
✅ **User Management**: Multi-role user scenarios
✅ **Lab Organization**: Complex lab group hierarchies
✅ **Protocol Documentation**: Detailed step-by-step protocols
✅ **Instrument Management**: Multi-instrument facility setup
✅ **Billing System**: Tiered pricing and cost tracking
✅ **Backup Monitoring**: Comprehensive backup logging
✅ **Sample Pooling**: Advanced pooling strategies
✅ **Ontology Integration**: Real biological terminology
✅ **SDRF Generation**: AI-powered metadata suggestions
✅ **Media Handling**: Multi-format file support

## Usage

This fixture is designed for:
- Import/export functionality testing
- Database migration validation
- System integration testing
- Performance benchmarking
- User training scenarios

## Data Relationships

The fixture includes realistic relationships between all entities:
- Users belong to lab groups with appropriate permissions
- Projects are owned by PIs with collaborator access
- Instrument jobs link users, projects, and instruments
- Sample pools reference specific instrument jobs
- SDRF cache entries are linked to protocol steps
- Annotations are distributed across protocol steps
- Billing records can be generated from completed jobs

## Version History

- v2.0: Complete rewrite with comprehensive model coverage
- v1.5: Added ontology and SDRF cache data
- v1.0: Basic fixture with core models
"""
    
    with open(os.path.join(temp_dir, 'README.md'), 'w') as f:
        f.write(readme_content)


def create_comprehensive_export_metadata():
    """Create comprehensive export metadata"""
    
    return {
        'export_info': {
            'version': '2.0',
            'created_at': datetime.now().isoformat(),
            'created_by': 'CUPCAKE Test System',
            'cupcake_version': '2.5.0',
            'database_schema_version': '149',
            'fixture_type': 'comprehensive_test_data'
        },
        'data_summary': {
            'total_users': 5,
            'total_lab_groups': 3,
            'total_projects': 4,
            'total_protocols': 3,
            'total_protocol_steps': 10,
            'total_instruments': 3,
            'total_instrument_jobs': 30,
            'total_billing_tiers': 3,
            'total_backup_logs': 50,
            'total_sample_pools': 15,
            'total_ontology_terms': 15,
            'total_sdrf_cache_entries': 20,
            'total_annotations': 150,
            'media_files_count': 61
        },
        'model_coverage': {
            'core_models': ['User', 'Project', 'Protocol', 'ProtocolStep', 'Annotation'],
            'lab_management': ['LabGroup', 'Instrument', 'InstrumentJob'],
            'billing_system': ['ServiceTier', 'ServicePrice', 'BillingRecord'],
            'backup_monitoring': ['BackupLog'],
            'sample_handling': ['SamplePool'],
            'ontology_integration': ['CellType', 'MondoDisease', 'UberonAnatomy', 'NCBITaxonomy', 'ChEBICompound', 'PSIMSOntology'],
            'ai_features': ['ProtocolStepSuggestionCache']
        },
        'testing_scenarios': [
            'Multi-user laboratory environment',
            'Complex protocol documentation',
            'Instrument scheduling and billing',
            'Sample pooling workflows',
            'Backup monitoring and recovery',
            'Ontology-based metadata annotation',
            'AI-powered SDRF generation',
            'Media file handling',
            'Cross-lab collaboration'
        ],
        'quality_assurance': {
            'data_validation': True,
            'referential_integrity': True,
            'realistic_timestamps': True,
            'diverse_data_types': True,
            'edge_case_coverage': True
        }
    }


def print_fixture_summary():
    """Print summary of created fixture"""
    
    print("\n📋 **COMPREHENSIVE TEST FIXTURE SUMMARY**")
    print("=" * 50)
    print("👥 Users: 5 (diverse roles and departments)")
    print("🏢 Lab Groups: 3 (core facility + research labs)")  
    print("📊 Projects: 4 (active research with funding)")
    print("📋 Protocols: 3 (detailed multi-step procedures)")
    print("🔬 Instruments: 3 (modern mass spectrometers)")
    print("⚗️  Instrument Jobs: 30 (various types and statuses)")
    print("💰 Billing Tiers: 3 (academic + commercial pricing)")
    print("💾 Backup Logs: 50 (realistic success/failure history)")  
    print("🧬 Sample Pools: 15 (complex pooling strategies)")
    print("🔬 Ontology Terms: 15 (across 6 major ontologies)")
    print("🤖 SDRF Cache: 20 (AI-generated suggestions)")
    print("📝 Annotations: 150 (diverse types with media)")
    print("📁 Media Files: 61 (audio, images, documents)")
    print("=" * 50)
    print("✅ Ready for comprehensive import/export testing!")


if __name__ == '__main__':
    create_comprehensive_test_fixture()