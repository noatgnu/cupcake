#!/usr/bin/env python3
"""
Create a complex machine-generated test fixture for import testing.
This creates a realistic laboratory scenario with 78+ annotations across
multiple protocols, sessions, instruments, and all annotation types.
"""

import json
import sqlite3
import zipfile
import tempfile
import shutil
import os
from datetime import datetime, timedelta
import uuid
import random


def create_complex_test_fixture():
    """Create comprehensive test fixture with complex laboratory data"""
    
    # Create temporary directory for building the archive
    temp_dir = tempfile.mkdtemp()
    
    try:
        # Create the SQLite database with comprehensive test data
        sqlite_path = os.path.join(temp_dir, 'user_data.sqlite')
        create_complex_database(sqlite_path)
        
        # Create media files for different annotation types
        media_dir = os.path.join(temp_dir, 'media')
        create_complex_media_files(media_dir)
        
        # Create comprehensive export metadata
        metadata = create_export_metadata()
        
        with open(os.path.join(temp_dir, 'export_metadata.json'), 'w') as f:
            json.dump(metadata, f, indent=2)
        
        # Create the ZIP archive
        archive_path = 'test_fixture_zip.zip'
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


def create_complex_database(sqlite_path):
    """Create SQLite database with comprehensive laboratory data"""
    conn = sqlite3.connect(sqlite_path)
    
    # Create all necessary tables with proper schema
    create_database_schema(conn)
    
    # Insert comprehensive test data
    insert_test_data(conn)
    
    conn.commit()
    conn.close()


def create_database_schema(conn):
    """Create comprehensive database schema matching Django models"""
    
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
            group_name TEXT NOT NULL,
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
    
    # Annotations - the main table we need many of
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
    
    # Instrument Usage
    conn.execute('''
        CREATE TABLE export_instrument_usage (
            id INTEGER PRIMARY KEY,
            instrument_id INTEGER,
            annotation_id INTEGER,
            user_id INTEGER,
            time_started TEXT,
            time_ended TEXT,
            description TEXT,
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
    
    # Metadata
    conn.execute('''
        CREATE TABLE export_metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')


def insert_test_data(conn):
    """Insert comprehensive test data representing a complex laboratory scenario"""
    
    # Base timestamp for consistent data
    base_time = datetime(2025, 1, 1, 9, 0, 0)
    
    # 1. Insert Users (lab members)
    users = [
        (1, 'dr_smith', 'smith@lab.edu', 'Dr. Sarah', 'Smith', 1, 1, base_time.isoformat()),
        (2, 'tech_jones', 'jones@lab.edu', 'Mike', 'Jones', 0, 1, base_time.isoformat()),
        (3, 'student_alice', 'alice@lab.edu', 'Alice', 'Johnson', 0, 1, base_time.isoformat()),
        (4, 'researcher_bob', 'bob@lab.edu', 'Dr. Bob', 'Wilson', 0, 1, base_time.isoformat()),
    ]
    
    for user in users:
        conn.execute('''INSERT INTO export_users 
                       (id, username, email, first_name, last_name, is_staff, is_active, date_joined) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', user)
    
    # 2. Insert Lab Groups
    lab_groups = [
        (1, 'Proteomics Lab', 'Advanced protein analysis and characterization', 1, 1, 'freezer_room_a', None, base_time.isoformat(), base_time.isoformat()),
        (2, 'Biochemistry Core', 'General biochemical analysis services', 1, 1, 'chemical_storage', None, base_time.isoformat(), base_time.isoformat()),
    ]
    
    for group in lab_groups:
        conn.execute('''INSERT INTO export_lab_groups 
                       (id, group_name, description, group_leader_id, is_professional, service_storage, default_storage_id, created_at, updated_at) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', group)
    
    # 3. Insert Projects
    projects = [
        (1, 'Protein Folding Study', 'Investigation of protein misfolding in neurodegenerative diseases', 1, 1, base_time.isoformat(), base_time.isoformat()),
        (2, 'Drug Discovery Pipeline', 'High-throughput screening for potential therapeutic compounds', 1, 1, base_time.isoformat(), base_time.isoformat()),
        (3, 'Metabolomics Analysis', 'Comprehensive metabolite profiling in disease models', 4, 1, base_time.isoformat(), base_time.isoformat()),
    ]
    
    for project in projects:
        conn.execute('''INSERT INTO export_projects 
                       (id, project_name, project_description, owner_id, enabled, created_at, updated_at) 
                       VALUES (?, ?, ?, ?, ?, ?, ?)''', project)
    
    # 4. Insert Instruments
    instruments = [
        (1, 'LC-MS/MS Orbitrap', 'High-resolution liquid chromatography mass spectrometer', None, 1, 7, 1, base_time.isoformat(), base_time.isoformat()),
        (2, 'Fluorescence Microscope', 'Advanced fluorescence imaging system with live cell capabilities', None, 1, 3, 1, base_time.isoformat(), base_time.isoformat()),
        (3, 'PCR Thermocycler', 'Real-time PCR system for gene expression analysis', None, 1, 1, 1, base_time.isoformat(), base_time.isoformat()),
        (4, 'Protein Crystallization Robot', 'Automated protein crystallization screening system', None, 1, 14, 0, base_time.isoformat(), base_time.isoformat()),
        (5, 'Cell Culture Hood', 'Sterile cell culture work environment', None, 1, 0, 1, base_time.isoformat(), base_time.isoformat()),
        (6, 'Spectrophotometer', 'UV-Vis spectrophotometer for concentration measurements', None, 1, 0, 1, base_time.isoformat(), base_time.isoformat()),
    ]
    
    for instrument in instruments:
        conn.execute('''INSERT INTO export_instruments 
                       (id, instrument_name, instrument_description, image, enabled, max_days_ahead_pre_approval, accepts_bookings, created_at, updated_at) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', instrument)
    
    # 5. Insert Complex Protocols
    protocols = [
        (1, 1001, 'Protein Purification via Ni-NTA Chromatography', 
         'Complete protocol for purifying His-tagged proteins using nickel-nitrilotriacetic acid chromatography columns', 
         '10.21769/BioProtoc.3892', 'https://bio-protocol.org/e3892', 'v2.1', 1, 1, base_time.isoformat(), 'hash_001'),
        
        (2, 1002, 'Western Blot Analysis Protocol', 
         'Standard protocol for protein detection via western blotting with enhanced chemiluminescence', 
         '10.21769/BioProtoc.3893', 'https://bio-protocol.org/e3893', 'v1.5', 1, 1, base_time.isoformat(), 'hash_002'),
        
        (3, 1003, 'Cell Culture and Transfection Protocol', 
         'Protocol for maintaining mammalian cell cultures and performing lipofection-based transfections', 
         None, None, 'v3.0', 2, 1, base_time.isoformat(), 'hash_003'),
        
        (4, 1004, 'Mass Spectrometry Sample Preparation', 
         'Comprehensive sample preparation for LC-MS/MS proteomics analysis including digestion and cleanup', 
         '10.21769/BioProtoc.3894', 'https://bio-protocol.org/e3894', 'v2.0', 4, 1, base_time.isoformat(), 'hash_004'),
        
        (5, 1005, 'Fluorescence Microscopy Imaging Protocol', 
         'Standardized protocol for live cell fluorescence microscopy with temporal resolution', 
         None, None, 'v1.0', 3, 1, base_time.isoformat(), 'hash_005'),
    ]
    
    for protocol in protocols:
        conn.execute('''INSERT INTO export_protocols 
                       (id, protocol_id, protocol_title, protocol_description, protocol_doi, protocol_url, protocol_version_uri, user_id, enabled, protocol_created_on, model_hash) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', protocol)
    
    # 6. Insert Protocol Sections
    sections = [
        # Protein Purification Protocol (ID 1)
        (1, 1, 'Sample Preparation', 120, base_time.isoformat(), base_time.isoformat()),
        (2, 1, 'Column Equilibration', 30, base_time.isoformat(), base_time.isoformat()),
        (3, 1, 'Protein Binding', 45, base_time.isoformat(), base_time.isoformat()),
        (4, 1, 'Washing Steps', 60, base_time.isoformat(), base_time.isoformat()),
        (5, 1, 'Protein Elution', 40, base_time.isoformat(), base_time.isoformat()),
        (6, 1, 'Quality Control', 30, base_time.isoformat(), base_time.isoformat()),
        
        # Western Blot Protocol (ID 2)
        (7, 2, 'Sample Preparation', 90, base_time.isoformat(), base_time.isoformat()),
        (8, 2, 'SDS-PAGE Electrophoresis', 120, base_time.isoformat(), base_time.isoformat()),
        (9, 2, 'Transfer to Membrane', 90, base_time.isoformat(), base_time.isoformat()),
        (10, 2, 'Blocking and Antibody Incubation', 180, base_time.isoformat(), base_time.isoformat()),
        (11, 2, 'Detection and Imaging', 45, base_time.isoformat(), base_time.isoformat()),
        
        # Cell Culture Protocol (ID 3)
        (12, 3, 'Cell Maintenance', 60, base_time.isoformat(), base_time.isoformat()),
        (13, 3, 'Transfection Setup', 45, base_time.isoformat(), base_time.isoformat()),
        (14, 3, 'Post-transfection Analysis', 30, base_time.isoformat(), base_time.isoformat()),
        
        # Mass Spec Prep Protocol (ID 4)
        (15, 4, 'Sample Digestion', 180, base_time.isoformat(), base_time.isoformat()),
        (16, 4, 'Cleanup and Concentration', 90, base_time.isoformat(), base_time.isoformat()),
        (17, 4, 'LC-MS Analysis', 120, base_time.isoformat(), base_time.isoformat()),
        
        # Microscopy Protocol (ID 5)
        (18, 5, 'Sample Preparation', 45, base_time.isoformat(), base_time.isoformat()),
        (19, 5, 'Imaging Setup', 30, base_time.isoformat(), base_time.isoformat()),
        (20, 5, 'Time-lapse Acquisition', 240, base_time.isoformat(), base_time.isoformat()),
    ]
    
    for section in sections:
        conn.execute('''INSERT INTO export_protocol_sections 
                       (id, protocol_id, section_description, section_duration, created_at, updated_at) 
                       VALUES (?, ?, ?, ?, ?, ?)''', section)
    
    # 7. Insert Protocol Steps (many steps per protocol)
    steps = []
    step_id = 1
    
    # Protocol 1 Steps (Protein Purification) - 15 steps
    protocol_1_steps = [
        (step_id, 1, 101, 'Prepare lysis buffer with protease inhibitors', 1, 20, None, 1, None),
        (step_id+1, 1, 102, 'Harvest cells by centrifugation at 4000 rpm for 10 min', 1, 15, step_id, 1, None),
        (step_id+2, 1, 103, 'Resuspend cell pellet in lysis buffer', 1, 10, step_id+1, 1, None),
        (step_id+3, 1, 104, 'Lyse cells by sonication (3x 30s pulses)', 1, 15, step_id+2, 1, None),
        (step_id+4, 1, 105, 'Clarify lysate by centrifugation at 12000 rpm for 30 min', 1, 35, step_id+3, 1, None),
        (step_id+5, 1, 106, 'Equilibrate Ni-NTA column with binding buffer', 2, 10, step_id+4, 1, None),
        (step_id+6, 1, 107, 'Load clarified lysate onto column', 3, 15, step_id+5, 1, None),
        (step_id+7, 1, 108, 'Wash column with 10 column volumes of wash buffer', 4, 20, step_id+6, 1, None),
        (step_id+8, 1, 109, 'Wash with high salt buffer to remove contaminants', 4, 15, step_id+7, 1, None),
        (step_id+9, 1, 110, 'Elute protein with increasing imidazole concentrations', 5, 25, step_id+8, 1, None),
        (step_id+10, 1, 111, 'Collect elution fractions and check by SDS-PAGE', 5, 10, step_id+9, 1, None),
        (step_id+11, 1, 112, 'Pool fractions containing pure protein', 5, 5, step_id+10, 1, None),
        (step_id+12, 1, 113, 'Measure protein concentration by Bradford assay', 6, 15, step_id+11, 1, None),
        (step_id+13, 1, 114, 'Analyze protein purity by SDS-PAGE and staining', 6, 10, step_id+12, 1, None),
        (step_id+14, 1, 115, 'Store purified protein at -80°C in aliquots', 6, 5, step_id+13, 1, None),
    ]
    
    steps.extend([(s[0], s[1], s[2], s[3], s[4], s[5], s[6], s[7], s[8], base_time.isoformat(), base_time.isoformat()) for s in protocol_1_steps])
    step_id += 15
    
    # Protocol 2 Steps (Western Blot) - 12 steps
    protocol_2_steps = [
        (step_id, 2, 201, 'Prepare protein samples in loading buffer', 7, 15, None, 1, None),
        (step_id+1, 2, 202, 'Heat samples at 95°C for 5 minutes', 7, 8, step_id, 1, None),
        (step_id+2, 2, 203, 'Load samples onto SDS-PAGE gel', 8, 10, step_id+1, 1, None),
        (step_id+3, 2, 204, 'Run electrophoresis at 120V for 90 minutes', 8, 95, step_id+2, 1, None),
        (step_id+4, 2, 205, 'Transfer proteins to PVDF membrane', 9, 90, step_id+3, 1, None),
        (step_id+5, 2, 206, 'Block membrane with 5% milk for 1 hour', 10, 65, step_id+4, 1, None),
        (step_id+6, 2, 207, 'Incubate with primary antibody overnight', 10, 720, step_id+5, 1, None),
        (step_id+7, 2, 208, 'Wash membrane 3x with TBST', 10, 15, step_id+6, 1, None),
        (step_id+8, 2, 209, 'Incubate with HRP-conjugated secondary antibody', 10, 60, step_id+7, 1, None),
        (step_id+9, 2, 210, 'Wash membrane 3x with TBST', 10, 15, step_id+8, 1, None),
        (step_id+10, 2, 211, 'Apply ECL substrate and expose to film', 11, 15, step_id+9, 1, None),
        (step_id+11, 2, 212, 'Develop film and analyze band intensities', 11, 30, step_id+10, 1, None),
    ]
    
    steps.extend([(s[0], s[1], s[2], s[3], s[4], s[5], s[6], s[7], s[8], base_time.isoformat(), base_time.isoformat()) for s in protocol_2_steps])
    step_id += 12
    
    # Protocol 3 Steps (Cell Culture) - 8 steps
    protocol_3_steps = [
        (step_id, 3, 301, 'Warm media and reagents to 37°C', 12, 15, None, 1, None),
        (step_id+1, 3, 302, 'Aspirate old media from culture dishes', 12, 5, step_id, 1, None),
        (step_id+2, 3, 303, 'Add fresh media to cells', 12, 5, step_id+1, 1, None),
        (step_id+3, 3, 304, 'Prepare transfection complexes', 13, 20, step_id+2, 1, None),
        (step_id+4, 3, 305, 'Add transfection complexes to cells dropwise', 13, 10, step_id+3, 1, None),
        (step_id+5, 3, 306, 'Incubate cells for 4-6 hours', 13, 300, step_id+4, 1, None),
        (step_id+6, 3, 307, 'Replace media with fresh media', 13, 10, step_id+5, 1, None),
        (step_id+7, 3, 308, 'Analyze transfection efficiency by fluorescence', 14, 30, step_id+6, 1, None),
    ]
    
    steps.extend([(s[0], s[1], s[2], s[3], s[4], s[5], s[6], s[7], s[8], base_time.isoformat(), base_time.isoformat()) for s in protocol_3_steps])
    step_id += 8
    
    # Protocol 4 Steps (Mass Spec Prep) - 10 steps
    protocol_4_steps = [
        (step_id, 4, 401, 'Reduce protein disulfide bonds with TCEP', 15, 30, None, 1, None),
        (step_id+1, 4, 402, 'Alkylate cysteine residues with iodoacetamide', 15, 45, step_id, 1, None),
        (step_id+2, 4, 403, 'Digest proteins with trypsin overnight', 15, 720, step_id+1, 1, None),
        (step_id+3, 4, 404, 'Quench digestion with formic acid', 15, 5, step_id+2, 1, None),
        (step_id+4, 4, 405, 'Clean up peptides using C18 columns', 16, 45, step_id+3, 1, None),
        (step_id+5, 4, 406, 'Dry peptides in SpeedVac concentrator', 16, 60, step_id+4, 1, None),
        (step_id+6, 4, 407, 'Resuspend peptides in 0.1% formic acid', 16, 10, step_id+5, 1, None),
        (step_id+7, 4, 408, 'Load samples onto LC-MS/MS system', 17, 15, step_id+6, 1, None),
        (step_id+8, 4, 409, 'Run 120-minute gradient LC-MS/MS analysis', 17, 130, step_id+7, 1, None),
        (step_id+9, 4, 410, 'Process raw data for protein identification', 17, 60, step_id+8, 1, None),
    ]
    
    steps.extend([(s[0], s[1], s[2], s[3], s[4], s[5], s[6], s[7], s[8], base_time.isoformat(), base_time.isoformat()) for s in protocol_4_steps])
    step_id += 10
    
    # Protocol 5 Steps (Microscopy) - 6 steps
    protocol_5_steps = [
        (step_id, 5, 501, 'Prepare cells on imaging-grade coverslips', 18, 30, None, 1, None),
        (step_id+1, 5, 502, 'Mount coverslips in perfusion chamber', 18, 15, step_id, 1, None),
        (step_id+2, 5, 503, 'Set up microscope with appropriate filters', 19, 20, step_id+1, 1, None),
        (step_id+3, 5, 504, 'Focus and select regions of interest', 19, 10, step_id+2, 1, None),
        (step_id+4, 5, 505, 'Start time-lapse acquisition', 20, 5, step_id+3, 1, None),
        (step_id+5, 5, 506, 'Monitor and adjust focus during acquisition', 20, 235, step_id+4, 1, None),
    ]
    
    steps.extend([(s[0], s[1], s[2], s[3], s[4], s[5], s[6], s[7], s[8], base_time.isoformat(), base_time.isoformat()) for s in protocol_5_steps])
    
    # Insert all steps
    for step in steps:
        conn.execute('''INSERT INTO export_protocol_steps 
                       (id, protocol_id, step_id, step_description, step_section_id, step_duration, previous_step_id, original, branch_from_id, created_at, updated_at) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', step)
    
    # 8. Insert Sessions (experiment sessions)
    sessions = [
        (1, str(uuid.uuid4()), 'Protein Purification Experiment - Batch A', 1, base_time.isoformat(), base_time.isoformat(), 
         base_time.isoformat(), (base_time + timedelta(hours=8)).isoformat(), 0),
        (2, str(uuid.uuid4()), 'Western Blot Analysis - Target Protein', 1, (base_time + timedelta(days=1)).isoformat(), (base_time + timedelta(days=1)).isoformat(),
         (base_time + timedelta(days=1)).isoformat(), (base_time + timedelta(days=2)).isoformat(), 0),
        (3, str(uuid.uuid4()), 'Cell Transfection - GFP Reporter', 1, (base_time + timedelta(days=2)).isoformat(), (base_time + timedelta(days=2)).isoformat(),
         (base_time + timedelta(days=2)).isoformat(), (base_time + timedelta(days=2, hours=6)).isoformat(), 0),
        (4, str(uuid.uuid4()), 'Mass Spec Analysis - Proteomics Study', 1, (base_time + timedelta(days=3)).isoformat(), (base_time + timedelta(days=3)).isoformat(),
         (base_time + timedelta(days=3)).isoformat(), (base_time + timedelta(days=3, hours=5)).isoformat(), 0),
        (5, str(uuid.uuid4()), 'Live Cell Imaging - Dynamics Study', 1, (base_time + timedelta(days=4)).isoformat(), (base_time + timedelta(days=4)).isoformat(),
         (base_time + timedelta(days=4)).isoformat(), (base_time + timedelta(days=4, hours=12)).isoformat(), 0),
    ]
    
    for session in sessions:
        conn.execute('''INSERT INTO export_sessions 
                       (id, unique_id, name, enabled, created_at, updated_at, started_at, ended_at, processing) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', session)
    
    # 9. Link sessions to protocols
    session_protocols = [
        (1, 1, 1), (2, 2, 2), (3, 3, 3), (4, 4, 4), (5, 5, 5)
    ]
    
    for sp in session_protocols:
        conn.execute('''INSERT INTO export_session_protocols (id, session_id, protocol_id) VALUES (?, ?, ?)''', sp)
    
    # 10. Insert Reagents and Storage
    reagents = [
        (1, 'Imidazole', 'Competitive inhibitor for His-tag purification', '68-94-0', 68.08, base_time.isoformat(), base_time.isoformat()),
        (2, 'TCEP', 'Tris(2-carboxyethyl)phosphine reducing agent', '51805-45-9', 286.65, base_time.isoformat(), base_time.isoformat()),
        (3, 'Trypsin', 'Proteolytic enzyme for protein digestion', '9002-07-7', 23800.0, base_time.isoformat(), base_time.isoformat()),
        (4, 'Lipofectamine 2000', 'Cationic lipid transfection reagent', None, None, base_time.isoformat(), base_time.isoformat()),
        (5, 'Anti-beta-actin antibody', 'Primary antibody for western blot loading control', None, None, base_time.isoformat(), base_time.isoformat()),
    ]
    
    for reagent in reagents:
        conn.execute('''INSERT INTO export_reagents 
                       (id, reagent_name, reagent_description, reagent_cas_number, reagent_molecular_weight, created_at, updated_at) 
                       VALUES (?, ?, ?, ?, ?, ?, ?)''', reagent)
    
    # Storage objects
    storage_objects = [
        (1, 'Freezer Box A1', 'freezer_box', 'Main -80°C freezer, position A1', 1, None, base_time.isoformat(), base_time.isoformat()),
        (2, 'Reagent Shelf B2', 'shelf', 'Chemical storage room, shelf B2', 1, None, base_time.isoformat(), base_time.isoformat()),
        (3, 'Cold Room Rack C3', 'rack', '4°C cold room, rack C3', 2, None, base_time.isoformat(), base_time.isoformat()),
    ]
    
    for storage in storage_objects:
        conn.execute('''INSERT INTO export_storage_objects 
                       (id, object_name, object_type, object_description, user_id, png_base64, created_at, updated_at) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', storage)
    
    # 11. Insert Annotation Folders (organized storage for annotations)
    folders = [
        (1, 1, None, None, 'Purification Results', None, 0, 1, base_time.isoformat(), base_time.isoformat()),
        (2, 1, None, None, 'Quality Control Data', 1, 0, 1, base_time.isoformat(), base_time.isoformat()),
        (3, 2, None, None, 'Western Blot Images', None, 0, 1, base_time.isoformat(), base_time.isoformat()),
        (4, 3, None, None, 'Transfection Efficiency', None, 0, 2, base_time.isoformat(), base_time.isoformat()),
        (5, 4, None, None, 'MS Raw Data', None, 0, 4, base_time.isoformat(), base_time.isoformat()),
        (6, 5, None, None, 'Time-lapse Movies', None, 0, 3, base_time.isoformat(), base_time.isoformat()),
        (7, None, 1, None, 'LC-MS/MS Analysis', None, 1, 4, base_time.isoformat(), base_time.isoformat()),
        (8, None, 2, None, 'Fluorescence Images', None, 1, 3, base_time.isoformat(), base_time.isoformat()),
    ]
    
    for folder in folders:
        conn.execute('''INSERT INTO export_annotation_folders 
                       (id, session_id, instrument_id, stored_reagent_id, folder_name, parent_folder_id, is_shared_document_folder, owner_id, created_at, updated_at) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', folder)
    
    # 12. NOW CREATE 78+ ANNOTATIONS across all types and contexts
    create_comprehensive_annotations(conn, base_time)
    
    # 13. Insert Tags
    tags = [
        (1, 'proteomics', 'Protein analysis experiments', base_time.isoformat(), base_time.isoformat()),
        (2, 'cell_culture', 'Cell culture related protocols', base_time.isoformat(), base_time.isoformat()),
        (3, 'mass_spectrometry', 'Mass spectrometry analysis', base_time.isoformat(), base_time.isoformat()),
        (4, 'microscopy', 'Microscopy and imaging', base_time.isoformat(), base_time.isoformat()),
        (5, 'biochemistry', 'General biochemical procedures', base_time.isoformat(), base_time.isoformat()),
    ]
    
    for tag in tags:
        conn.execute('''INSERT INTO export_tags (id, tag_name, tag_description, created_at, updated_at) VALUES (?, ?, ?, ?, ?)''', tag)
    
    # Protocol tags
    protocol_tags = [
        (1, 1, 1, base_time.isoformat(), base_time.isoformat()),
        (2, 1, 5, base_time.isoformat(), base_time.isoformat()),
        (3, 2, 1, base_time.isoformat(), base_time.isoformat()),
        (4, 3, 2, base_time.isoformat(), base_time.isoformat()),
        (5, 4, 1, base_time.isoformat(), base_time.isoformat()),
        (6, 4, 3, base_time.isoformat(), base_time.isoformat()),
        (7, 5, 4, base_time.isoformat(), base_time.isoformat()),
        (8, 5, 2, base_time.isoformat(), base_time.isoformat()),
    ]
    
    for pt in protocol_tags:
        conn.execute('''INSERT INTO export_protocol_tags (id, protocol_id, tag_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)''', pt)
    
    # 14. Insert metadata
    metadata_entries = [
        ('version', '3.0'),
        ('export_type', 'comprehensive_test'),
        ('total_annotations', '78'),
        ('protocols_count', '5'),
        ('sessions_count', '5'),
        ('instruments_count', '6'),
    ]
    
    for entry in metadata_entries:
        conn.execute('INSERT INTO export_metadata (key, value) VALUES (?, ?)', entry)


def create_comprehensive_annotations(conn, base_time):
    """Create 78+ annotations across all types and contexts"""
    
    annotations = []
    ann_id = 1
    
    # All possible annotation types
    ann_types = ["text", "file", "image", "video", "audio", "sketch", "other", "checklist", "counter", "table"]
    
    # Session 1 annotations (Protein Purification) - 20 annotations
    session_1_annotations = [
        # Step-specific annotations
        (ann_id, 1, 1, None, "Started protein purification with 2L of E. coli culture (OD600 = 1.8)", None, "text", 1, 1, "Initial Culture Assessment", "High cell density achieved", 0, None, "en", None, 0, 0, base_time.isoformat(), base_time.isoformat()),
        (ann_id+1, 1, 2, None, "Cell pellet weight: 12.5g wet weight", None, "counter", 1, 1, "Cell Pellet Mass", "Good yield from culture", 0, None, "en", None, 0, 0, base_time.isoformat(), base_time.isoformat()),
        (ann_id+2, 1, 3, None, "Lysis buffer composition verified by pH meter", "annotations/lysis_buffer_ph.jpg", "image", 1, 1, "Buffer QC", "pH 7.4 confirmed", 0, None, "en", None, 0, 0, base_time.isoformat(), base_time.isoformat()),
        (ann_id+3, 1, 4, None, "Sonication parameters: 30% amplitude, 3x30s with 1min cooling", "annotations/sonication_audio.wav", "audio", 2, 1, "Sonication Record", "Proper lysis achieved", 0, None, "en", None, 0, 0, base_time.isoformat(), base_time.isoformat()),
        (ann_id+4, 1, 5, None, "Lysate clarity improved significantly after centrifugation", "annotations/lysate_before_after.mp4", "video", 2, 1, "Clarification Video", "Clear supernatant obtained", 0, None, "en", None, 0, 0, base_time.isoformat(), base_time.isoformat()),
        (ann_id+5, 1, 6, None, "Column bed volume: 5mL, equilibrated with 50mL binding buffer", None, "text", 1, 1, "Column Prep", "Ready for loading", 0, None, "en", None, 0, 0, base_time.isoformat(), base_time.isoformat()),
        (ann_id+6, 1, 7, None, "Loading flowrate: 1mL/min, back-pressure stable", "annotations/loading_pressure.csv", "file", 1, 1, "Loading Parameters", "Stable conditions", 0, None, "en", None, 0, 0, base_time.isoformat(), base_time.isoformat()),
        (ann_id+7, 1, 8, None, "Wash fractions collected and UV280 monitored", "annotations/wash_fractions_sketch.png", "sketch", 1, 2, "Wash Profile", "Baseline achieved", 0, None, "en", None, 0, 0, base_time.isoformat(), base_time.isoformat()),
        (ann_id+8, 1, 9, None, "High salt wash removed most contaminating proteins", None, "text", 2, 2, "Contamination Removal", "Improved purity expected", 0, None, "en", None, 0, 0, base_time.isoformat(), base_time.isoformat()),
        (ann_id+9, 1, 10, None, "Elution gradient: 50mM to 500mM imidazole over 20mL", "annotations/elution_gradient.jpg", "image", 1, 2, "Elution Profile", "Sharp protein peak at 200mM", 0, None, "en", None, 0, 0, base_time.isoformat(), base_time.isoformat()),
        (ann_id+10, 1, 11, None, "SDS-PAGE shows single band at expected molecular weight (~45kDa)", "annotations/sds_page_gel.jpg", "image", 1, 2, "Purity Check", "High purity achieved", 0, None, "en", None, 0, 0, base_time.isoformat(), base_time.isoformat()),
        (ann_id+11, 1, 12, None, "Pooled fractions 8-12 (total volume: 25mL)", None, "text", 1, 2, "Fraction Pooling", "Best fractions selected", 0, None, "en", None, 0, 0, base_time.isoformat(), base_time.isoformat()),
        (ann_id+12, 1, 13, None, "Bradford assay results", "annotations/bradford_table.xlsx", "table", 1, 2, "Concentration Data", "2.5 mg/mL final concentration", 0, None, "en", None, 0, 0, base_time.isoformat(), base_time.isoformat()),
        (ann_id+13, 1, 14, None, "Final purity assessment by gel densitometry", "annotations/gel_analysis.pdf", "file", 1, 2, "Purity Analysis", ">95% pure protein", 0, None, "en", None, 0, 0, base_time.isoformat(), base_time.isoformat()),
        (ann_id+14, 1, 15, None, "Aliquoted into 100μL portions and flash frozen", None, "checklist", 1, 2, "Storage Checklist", "Proper storage completed", 0, None, "en", None, 0, 0, base_time.isoformat(), base_time.isoformat()),
        
        # Session-level annotations
        (ann_id+15, 1, None, None, "Overall purification yield: 62.5mg from 2L culture", None, "text", 1, 1, "Final Yield", "Excellent yield achieved", 0, None, "en", None, 0, 0, base_time.isoformat(), base_time.isoformat()),
        (ann_id+16, 1, None, None, "Protocol modifications for next run", "annotations/protocol_notes.txt", "file", 1, 1, "Protocol Notes", "Optimizations identified", 0, None, "en", None, 0, 0, base_time.isoformat(), base_time.isoformat()),
        (ann_id+17, 1, None, None, "Temperature log during purification", "annotations/temp_log.csv", "file", 2, 1, "Temperature Monitor", "Stable 4°C maintained", 0, None, "en", None, 0, 0, base_time.isoformat(), base_time.isoformat()),
        (ann_id+18, 1, None, None, "Laboratory notebook scan", "annotations/lab_notebook_page1.pdf", "file", 1, 1, "Lab Notes", "Complete record", 0, None, "en", None, 0, 0, base_time.isoformat(), base_time.isoformat()),
        (ann_id+19, 1, None, None, "Issues encountered and solutions", None, "other", 2, 1, "Troubleshooting", "Minor pump issue resolved", 0, None, "en", None, 0, 0, base_time.isoformat(), base_time.isoformat()),
    ]
    
    annotations.extend(session_1_annotations)
    ann_id += 20
    
    # Session 2 annotations (Western Blot) - 16 annotations
    session_2_annotations = [
        (ann_id, 2, 16, None, "Sample preparation: protein samples normalized to 50μg", None, "text", 1, 3, "Sample Prep", "Equal loading prepared", 0, None, "en", None, 0, 0, (base_time + timedelta(days=1)).isoformat(), (base_time + timedelta(days=1)).isoformat()),
        (ann_id+1, 2, 17, None, "Loading buffer composition verified", "annotations/loading_buffer_recipe.txt", "file", 1, 3, "Buffer Recipe", "Standard protocol used", 0, None, "en", None, 0, 0, (base_time + timedelta(days=1)).isoformat(), (base_time + timedelta(days=1)).isoformat()),
        (ann_id+2, 2, 18, None, "12% polyacrylamide gel prepared fresh", None, "text", 2, 3, "Gel Preparation", "Optimal resolution expected", 0, None, "en", None, 0, 0, (base_time + timedelta(days=1)).isoformat(), (base_time + timedelta(days=1)).isoformat()),
        (ann_id+3, 2, 19, None, "Electrophoresis run at constant voltage", "annotations/electrophoresis_video.mp4", "video", 1, 3, "Gel Run", "Clean protein separation", 0, None, "en", None, 0, 0, (base_time + timedelta(days=1)).isoformat(), (base_time + timedelta(days=1)).isoformat()),
        (ann_id+4, 2, 20, None, "Transfer efficiency checked with Ponceau S staining", "annotations/ponceau_stain.jpg", "image", 1, 3, "Transfer Check", "Complete transfer confirmed", 0, None, "en", None, 0, 0, (base_time + timedelta(days=1)).isoformat(), (base_time + timedelta(days=1)).isoformat()),
        (ann_id+5, 2, 21, None, "Blocking performed with 5% non-fat milk in TBST", None, "text", 1, 3, "Blocking", "Non-specific binding minimized", 0, None, "en", None, 0, 0, (base_time + timedelta(days=1)).isoformat(), (base_time + timedelta(days=1)).isoformat()),
        (ann_id+6, 2, 22, None, "Primary antibody: anti-target protein (1:1000 dilution)", None, "text", 1, 3, "Primary Ab", "Optimal dilution used", 0, None, "en", None, 0, 0, (base_time + timedelta(days=1)).isoformat(), (base_time + timedelta(days=1)).isoformat()),
        (ann_id+7, 2, 23, None, "Washing protocol strictly followed", "annotations/wash_timer_log.txt", "file", 2, 3, "Wash Log", "Complete wash cycles", 0, None, "en", None, 0, 0, (base_time + timedelta(days=1)).isoformat(), (base_time + timedelta(days=1)).isoformat()),
        (ann_id+8, 2, 24, None, "Secondary antibody: anti-rabbit HRP (1:5000)", None, "text", 1, 3, "Secondary Ab", "Strong signal expected", 0, None, "en", None, 0, 0, (base_time + timedelta(days=1)).isoformat(), (base_time + timedelta(days=1)).isoformat()),
        (ann_id+9, 2, 25, None, "ECL substrate applied evenly across membrane", "annotations/ecl_application.mp4", "video", 2, 3, "ECL Application", "Even coverage achieved", 0, None, "en", None, 0, 0, (base_time + timedelta(days=1)).isoformat(), (base_time + timedelta(days=1)).isoformat()),
        (ann_id+10, 2, 26, None, "Multiple exposure times tested", "annotations/exposure_times.jpg", "image", 1, 3, "Exposure Optimization", "5-minute exposure optimal", 0, None, "en", None, 0, 0, (base_time + timedelta(days=1)).isoformat(), (base_time + timedelta(days=1)).isoformat()),
        (ann_id+11, 2, 27, None, "Band intensity quantification", "annotations/band_quantification.xlsx", "table", 1, 3, "Quantification", "Significant protein expression", 0, None, "en", None, 0, 0, (base_time + timedelta(days=1)).isoformat(), (base_time + timedelta(days=1)).isoformat()),
        (ann_id+12, 2, None, None, "Beta-actin loading control shows equal loading", "annotations/actin_control.jpg", "image", 1, 3, "Loading Control", "Normalized results valid", 0, None, "en", None, 0, 0, (base_time + timedelta(days=1)).isoformat(), (base_time + timedelta(days=1)).isoformat()),
        (ann_id+13, 2, None, None, "Western blot statistical analysis", "annotations/statistics.pdf", "file", 4, 3, "Statistical Analysis", "Significant differences found", 0, None, "en", None, 0, 0, (base_time + timedelta(days=1)).isoformat(), (base_time + timedelta(days=1)).isoformat()),
        (ann_id+14, 2, None, None, "Experimental conditions summary", None, "other", 1, 3, "Experiment Summary", "Successful target detection", 0, None, "en", None, 0, 0, (base_time + timedelta(days=1)).isoformat(), (base_time + timedelta(days=1)).isoformat()),
        (ann_id+15, 2, None, None, "Membrane storage and archiving notes", None, "text", 2, 3, "Archive Notes", "Stored for future reference", 0, None, "en", None, 0, 0, (base_time + timedelta(days=1)).isoformat(), (base_time + timedelta(days=1)).isoformat()),
    ]
    
    annotations.extend(session_2_annotations)
    ann_id += 16
    
    # Session 3 annotations (Cell Culture/Transfection) - 14 annotations
    session_3_annotations = [
        (ann_id, 3, 28, None, "HEK293T cells at 70% confluency used for transfection", None, "text", 2, 4, "Cell Density", "Optimal for transfection", 0, None, "en", None, 0, 0, (base_time + timedelta(days=2)).isoformat(), (base_time + timedelta(days=2)).isoformat()),
        (ann_id+1, 3, 29, None, "Media warmed to exactly 37°C", "annotations/media_temp.jpg", "image", 2, 4, "Media Temperature", "Proper warming confirmed", 0, None, "en", None, 0, 0, (base_time + timedelta(days=2)).isoformat(), (base_time + timedelta(days=2)).isoformat()),
        (ann_id+2, 3, 30, None, "Fresh media added dropwise to avoid cell disturbance", "annotations/media_addition.mp4", "video", 2, 4, "Media Addition", "Gentle technique used", 0, None, "en", None, 0, 0, (base_time + timedelta(days=2)).isoformat(), (base_time + timedelta(days=2)).isoformat()),
        (ann_id+3, 3, 31, None, "Lipofectamine 2000:DNA ratio optimized at 3:1", None, "text", 2, 4, "Transfection Ratio", "Optimized for efficiency", 0, None, "en", None, 0, 0, (base_time + timedelta(days=2)).isoformat(), (base_time + timedelta(days=2)).isoformat()),
        (ann_id+4, 3, 32, None, "Transfection complexes incubated 20 minutes at RT", None, "text", 2, 4, "Complex Formation", "Proper complex formation", 0, None, "en", None, 0, 0, (base_time + timedelta(days=2)).isoformat(), (base_time + timedelta(days=2)).isoformat()),
        (ann_id+5, 3, 33, None, "Complexes added dropwise with gentle mixing", "annotations/complex_addition.mp4", "video", 2, 4, "Complex Addition", "Even distribution achieved", 0, None, "en", None, 0, 0, (base_time + timedelta(days=2)).isoformat(), (base_time + timedelta(days=2)).isoformat()),
        (ann_id+6, 3, 34, None, "Cells monitored for morphology changes", "annotations/cell_morphology_timelapse.mp4", "video", 3, 4, "Cell Monitoring", "Healthy cell appearance", 0, None, "en", None, 0, 0, (base_time + timedelta(days=2)).isoformat(), (base_time + timedelta(days=2)).isoformat()),
        (ann_id+7, 3, 35, None, "Media changed after 6 hours incubation", None, "text", 2, 4, "Media Change", "Toxicity minimized", 0, None, "en", None, 0, 0, (base_time + timedelta(days=2)).isoformat(), (base_time + timedelta(days=2)).isoformat()),
        (ann_id+8, 3, 36, None, "GFP fluorescence detected 24h post-transfection", "annotations/gfp_fluorescence.jpg", "image", 3, 4, "Transfection Success", "Strong GFP expression", 0, None, "en", None, 0, 0, (base_time + timedelta(days=2)).isoformat(), (base_time + timedelta(days=2)).isoformat()),
        (ann_id+9, 3, None, None, "Transfection efficiency estimated at 75%", "annotations/efficiency_count.xlsx", "table", 3, 4, "Efficiency Analysis", "High efficiency achieved", 0, None, "en", None, 0, 0, (base_time + timedelta(days=2)).isoformat(), (base_time + timedelta(days=2)).isoformat()),
        (ann_id+10, 3, None, None, "Cell viability check with trypan blue", "annotations/viability_assay.jpg", "image", 2, 4, "Viability Check", "95% cells viable", 0, None, "en", None, 0, 0, (base_time + timedelta(days=2)).isoformat(), (base_time + timedelta(days=2)).isoformat()),
        (ann_id+11, 3, None, None, "Fluorescence intensity measurements", "annotations/fluorescence_data.csv", "file", 3, 4, "Intensity Data", "Quantitative analysis", 0, None, "en", None, 0, 0, (base_time + timedelta(days=2)).isoformat(), (base_time + timedelta(days=2)).isoformat()),
        (ann_id+12, 3, None, None, "Protocol optimization notes for future experiments", None, "other", 2, 4, "Protocol Notes", "Successful transfection", 0, None, "en", None, 0, 0, (base_time + timedelta(days=2)).isoformat(), (base_time + timedelta(days=2)).isoformat()),
        (ann_id+13, 3, None, None, "Cells harvested for downstream analysis", None, "checklist", 2, 4, "Harvest Checklist", "Ready for analysis", 0, None, "en", None, 0, 0, (base_time + timedelta(days=2)).isoformat(), (base_time + timedelta(days=2)).isoformat()),
    ]
    
    annotations.extend(session_3_annotations)
    ann_id += 14
    
    # Session 4 annotations (Mass Spectrometry) - 15 annotations
    session_4_annotations = [
        (ann_id, 4, 37, None, "Protein samples reduced with 10mM TCEP at 56°C", None, "text", 4, 5, "Reduction Step", "Complete disulfide reduction", 0, None, "en", None, 0, 0, (base_time + timedelta(days=3)).isoformat(), (base_time + timedelta(days=3)).isoformat()),
        (ann_id+1, 4, 38, None, "Alkylation with 55mM iodoacetamide in dark", None, "text", 4, 5, "Alkylation", "Cysteine modification complete", 0, None, "en", None, 0, 0, (base_time + timedelta(days=3)).isoformat(), (base_time + timedelta(days=3)).isoformat()),
        (ann_id+2, 4, 39, None, "Trypsin digestion overnight at 37°C", "annotations/digestion_ph.jpg", "image", 4, 5, "Digestion Conditions", "Optimal pH maintained", 0, None, "en", None, 0, 0, (base_time + timedelta(days=3)).isoformat(), (base_time + timedelta(days=3)).isoformat()),
        (ann_id+3, 4, 40, None, "Digestion quenched with 1% formic acid", None, "text", 4, 5, "Digestion Stop", "Enzyme activity stopped", 0, None, "en", None, 0, 0, (base_time + timedelta(days=3)).isoformat(), (base_time + timedelta(days=3)).isoformat()),
        (ann_id+4, 4, 41, None, "C18 cleanup performed with 100% recovery", "annotations/cleanup_flowthrough.jpg", "image", 4, 5, "Sample Cleanup", "Complete peptide recovery", 0, None, "en", None, 0, 0, (base_time + timedelta(days=3)).isoformat(), (base_time + timedelta(days=3)).isoformat()),
        (ann_id+5, 4, 42, None, "SpeedVac concentration completed", "annotations/speedvac_log.txt", "file", 4, 5, "Concentration Log", "Samples concentrated 10x", 0, None, "en", None, 0, 0, (base_time + timedelta(days=3)).isoformat(), (base_time + timedelta(days=3)).isoformat()),
        (ann_id+6, 4, 43, None, "Peptides resuspended in LC-MS buffer", None, "text", 4, 5, "Resuspension", "Ready for MS analysis", 0, None, "en", None, 0, 0, (base_time + timedelta(days=3)).isoformat(), (base_time + timedelta(days=3)).isoformat()),
        (ann_id+7, 4, 44, None, "LC-MS/MS system calibrated and tested", "annotations/calibration_report.pdf", "file", 4, 7, "System Calibration", "Optimal performance achieved", 0, None, "en", None, 0, 0, (base_time + timedelta(days=3)).isoformat(), (base_time + timedelta(days=3)).isoformat()),
        (ann_id+8, 4, 45, None, "120-minute gradient optimization", "annotations/gradient_profile.jpg", "image", 4, 7, "Gradient Setup", "Optimal peptide separation", 0, None, "en", None, 0, 0, (base_time + timedelta(days=3)).isoformat(), (base_time + timedelta(days=3)).isoformat()),
        (ann_id+9, 4, 46, None, "MS1 and MS2 acquisition parameters set", "annotations/ms_parameters.txt", "file", 4, 7, "MS Parameters", "High resolution analysis", 0, None, "en", None, 0, 0, (base_time + timedelta(days=3)).isoformat(), (base_time + timedelta(days=3)).isoformat()),
        (ann_id+10, 4, 47, None, "Raw data processing with MaxQuant", "annotations/maxquant_log.txt", "file", 4, 5, "Data Processing", "High protein identification", 0, None, "en", None, 0, 0, (base_time + timedelta(days=3)).isoformat(), (base_time + timedelta(days=3)).isoformat()),
        (ann_id+11, 4, None, None, "Protein identification: 2,847 proteins with 1% FDR", "annotations/protein_ids.xlsx", "table", 4, 5, "Identification Results", "Comprehensive proteome coverage", 0, None, "en", None, 0, 0, (base_time + timedelta(days=3)).isoformat(), (base_time + timedelta(days=3)).isoformat()),
        (ann_id+12, 4, None, None, "LC performance monitoring", "annotations/lc_pressure_trace.csv", "file", 4, 7, "LC Performance", "Stable chromatography", 0, None, "en", None, 0, 0, (base_time + timedelta(days=3)).isoformat(), (base_time + timedelta(days=3)).isoformat()),
        (ann_id+13, 4, None, None, "Mass accuracy assessment", "annotations/mass_accuracy.pdf", "file", 4, 7, "Mass Accuracy", "Sub-ppm accuracy achieved", 0, None, "en", None, 0, 0, (base_time + timedelta(days=3)).isoformat(), (base_time + timedelta(days=3)).isoformat()),
        (ann_id+14, 4, None, None, "Quantitative analysis completed", "annotations/quant_results.xlsx", "table", 4, 5, "Quantification", "Significant protein changes", 0, None, "en", None, 0, 0, (base_time + timedelta(days=3)).isoformat(), (base_time + timedelta(days=3)).isoformat()),
    ]
    
    annotations.extend(session_4_annotations)
    ann_id += 15
    
    # Session 5 annotations (Microscopy) - 13 annotations
    session_5_annotations = [
        (ann_id, 5, 48, None, "Cells plated on glass-bottom dishes for imaging", None, "text", 3, 6, "Cell Plating", "Optimal density for imaging", 0, None, "en", None, 0, 0, (base_time + timedelta(days=4)).isoformat(), (base_time + timedelta(days=4)).isoformat()),
        (ann_id+1, 5, 49, None, "Imaging medium equilibrated with CO2", None, "text", 3, 6, "Medium Prep", "Physiological conditions", 0, None, "en", None, 0, 0, (base_time + timedelta(days=4)).isoformat(), (base_time + timedelta(days=4)).isoformat()),
        (ann_id+2, 5, 50, None, "Microscope setup with environmental chamber", "annotations/microscope_setup.jpg", "image", 3, 8, "Microscope Setup", "Temperature and CO2 controlled", 0, None, "en", None, 0, 0, (base_time + timedelta(days=4)).isoformat(), (base_time + timedelta(days=4)).isoformat()),
        (ann_id+3, 5, 51, None, "Multiple fields selected for time-lapse", "annotations/field_selection.jpg", "image", 3, 8, "Field Selection", "Representative areas chosen", 0, None, "en", None, 0, 0, (base_time + timedelta(days=4)).isoformat(), (base_time + timedelta(days=4)).isoformat()),
        (ann_id+4, 5, 52, None, "Acquisition parameters: 5-minute intervals", "annotations/acquisition_settings.txt", "file", 3, 8, "Acquisition Setup", "High temporal resolution", 0, None, "en", None, 0, 0, (base_time + timedelta(days=4)).isoformat(), (base_time + timedelta(days=4)).isoformat()),
        (ann_id+5, 5, 53, None, "Time-lapse acquisition started", "annotations/timelapse_start.mp4", "video", 3, 6, "Acquisition Start", "Stable imaging conditions", 0, None, "en", None, 0, 0, (base_time + timedelta(days=4)).isoformat(), (base_time + timedelta(days=4)).isoformat()),
        (ann_id+6, 5, 54, None, "Focus stability monitored throughout acquisition", "annotations/focus_drift.csv", "file", 3, 8, "Focus Monitor", "Minimal focus drift", 0, None, "en", None, 0, 0, (base_time + timedelta(days=4)).isoformat(), (base_time + timedelta(days=4)).isoformat()),
        (ann_id+7, 5, None, None, "Cell division events captured", "annotations/cell_division.mp4", "video", 3, 6, "Cell Division", "Multiple division events", 0, None, "en", None, 0, 0, (base_time + timedelta(days=4)).isoformat(), (base_time + timedelta(days=4)).isoformat()),
        (ann_id+8, 5, None, None, "Fluorescence intensity analysis", "annotations/intensity_analysis.xlsx", "table", 3, 6, "Intensity Data", "Dynamic protein localization", 0, None, "en", None, 0, 0, (base_time + timedelta(days=4)).isoformat(), (base_time + timedelta(days=4)).isoformat()),
        (ann_id+9, 5, None, None, "Cell tracking results", "annotations/cell_tracks.csv", "file", 3, 6, "Cell Tracking", "Complete cell lineages", 0, None, "en", None, 0, 0, (base_time + timedelta(days=4)).isoformat(), (base_time + timedelta(days=4)).isoformat()),
        (ann_id+10, 5, None, None, "Movie compilation of key events", "annotations/highlight_movie.mp4", "video", 3, 6, "Highlight Movie", "Key biological events", 0, None, "en", None, 0, 0, (base_time + timedelta(days=4)).isoformat(), (base_time + timedelta(days=4)).isoformat()),
        (ann_id+11, 5, None, None, "Statistical analysis of dynamics", "annotations/dynamics_stats.pdf", "file", 3, 6, "Statistical Analysis", "Significant patterns found", 0, None, "en", None, 0, 0, (base_time + timedelta(days=4)).isoformat(), (base_time + timedelta(days=4)).isoformat()),
        (ann_id+12, 5, None, None, "Experimental summary and conclusions", None, "other", 3, 6, "Experiment Summary", "Dynamic processes revealed", 0, None, "en", None, 0, 0, (base_time + timedelta(days=4)).isoformat(), (base_time + timedelta(days=4)).isoformat()),
    ]
    
    annotations.extend(session_5_annotations)
    
    # Total annotations so far: 20 + 16 + 14 + 15 + 13 = 78 annotations
    
    # Insert all annotations
    for annotation in annotations:
        conn.execute('''INSERT INTO export_annotations 
                       (id, session_id, step_id, stored_reagent_id, annotation, file, annotation_type, user_id, folder_id, annotation_name, summary, transcribed, transcription, language, translation, scratched, fixed, created_at, updated_at) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', annotation)
    
    # Add instrument usage records for relevant annotations
    instrument_usage = [
        (1, 1, 8, 1, (base_time + timedelta(hours=2)).isoformat(), (base_time + timedelta(hours=4)).isoformat(), "LC-MS/MS analysis for protein identification", base_time.isoformat(), base_time.isoformat()),
        (2, 2, 25, 1, (base_time + timedelta(days=1, hours=3)).isoformat(), (base_time + timedelta(days=1, hours=4)).isoformat(), "Fluorescence imaging for western blot", (base_time + timedelta(days=1)).isoformat(), (base_time + timedelta(days=1)).isoformat()),
        (3, 2, 87, 3, (base_time + timedelta(days=2, hours=1)).isoformat(), (base_time + timedelta(days=2, hours=7)).isoformat(), "Live cell fluorescence microscopy", (base_time + timedelta(days=2)).isoformat(), (base_time + timedelta(days=2)).isoformat()),
        (4, 1, 93, 4, (base_time + timedelta(days=3, hours=2)).isoformat(), (base_time + timedelta(days=3, hours=4)).isoformat(), "High-resolution mass spectrometry", (base_time + timedelta(days=3)).isoformat(), (base_time + timedelta(days=3)).isoformat()),
        (5, 2, 102, 3, (base_time + timedelta(days=4, hours=1)).isoformat(), (base_time + timedelta(days=4, hours=9)).isoformat(), "Time-lapse fluorescence microscopy", (base_time + timedelta(days=4)).isoformat(), (base_time + timedelta(days=4)).isoformat()),
    ]
    
    for usage in instrument_usage:
        conn.execute('''INSERT INTO export_instrument_usage 
                       (id, instrument_id, annotation_id, user_id, time_started, time_ended, description, created_at, updated_at) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', usage)


def create_complex_media_files(media_dir):
    """Create realistic media files for the annotations"""
    os.makedirs(media_dir, exist_ok=True)
    
    # Create subdirectory for annotations
    ann_dir = os.path.join(media_dir, 'annotations')
    os.makedirs(ann_dir, exist_ok=True)
    
    # Create various file types referenced in annotations
    files_to_create = [
        # Images
        ('lysis_buffer_ph.jpg', b'\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xFF\xDB\x00C\x00fake_jpeg_pH_meter_image'),
        ('lysate_before_after.mp4', b'\x00\x00\x00\x1Cftypmp41\x00\x00\x00\x00mp41isom\x00\x00\x00\x08freefake_mp4_lysate_comparison'),
        ('elution_gradient.jpg', b'\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xFF\xDB\x00C\x00fake_jpeg_chromatogram'),
        ('sds_page_gel.jpg', b'\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xFF\xDB\x00C\x00fake_jpeg_protein_gel'),
        ('ponceau_stain.jpg', b'\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xFF\xDB\x00C\x00fake_jpeg_membrane_stain'),
        ('gfp_fluorescence.jpg', b'\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xFF\xDB\x00C\x00fake_jpeg_gfp_cells'),
        ('microscope_setup.jpg', b'\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xFF\xDB\x00C\x00fake_jpeg_microscope'),
        
        # Videos
        ('sonication_audio.wav', b'RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00D\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00datafake_wav_sonication_sound'),
        ('electrophoresis_video.mp4', b'\x00\x00\x00\x1Cftypmp41\x00\x00\x00\x00mp41isom\x00\x00\x00\x08freefake_mp4_gel_electrophoresis'),
        ('complex_addition.mp4', b'\x00\x00\x00\x1Cftypmp41\x00\x00\x00\x00mp41isom\x00\x00\x00\x08freefake_mp4_transfection'),
        ('cell_division.mp4', b'\x00\x00\x00\x1Cftypmp41\x00\x00\x00\x00mp41isom\x00\x00\x00\x08freefake_mp4_cell_division'),
        ('timelapse_start.mp4', b'\x00\x00\x00\x1Cftypmp41\x00\x00\x00\x00mp41isom\x00\x00\x00\x08freefake_mp4_timelapse'),
        
        # Sketches and drawings
        ('wash_fractions_sketch.png', b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x10\x00\x00\x00\x10\x08\x06\x00\x00\x00\x1f\xf3\xffa\x00\x00\x00\x19tEXtSoftware\x00Adobe ImageReadyq\xc9e<fake_png_sketch'),
        
        # Data files and tables
        ('loading_pressure.csv', b'Time,Pressure_Bar,Flow_Rate_mL_min\n0,0.5,1.0\n5,1.2,1.0\n10,1.8,1.0\n15,2.1,1.0\n20,2.0,1.0\n'),
        ('bradford_table.xlsx', b'PK\x03\x04\x14\x00\x00\x00\x08\x00fake_excel_bradford_assay_data_with_concentrations'),
        ('band_quantification.xlsx', b'PK\x03\x04\x14\x00\x00\x00\x08\x00fake_excel_western_blot_band_intensity_data'),
        ('efficiency_count.xlsx', b'PK\x03\x04\x14\x00\x00\x00\x08\x00fake_excel_transfection_efficiency_counting_data'),
        ('protein_ids.xlsx', b'PK\x03\x04\x14\x00\x00\x00\x08\x00fake_excel_mass_spec_protein_identification_results'),
        ('intensity_analysis.xlsx', b'PK\x03\x04\x14\x00\x00\x00\x08\x00fake_excel_fluorescence_intensity_time_series'),
        ('quant_results.xlsx', b'PK\x03\x04\x14\x00\x00\x00\x08\x00fake_excel_quantitative_proteomics_results'),
        
        # Text and log files
        ('loading_buffer_recipe.txt', b'Loading Buffer Recipe:\n4x Laemmli Buffer\n- 250mM Tris-HCl pH 6.8\n- 8% SDS\n- 40% Glycerol\n- 0.4% Bromophenol Blue\n- 20% Beta-mercaptoethanol\n'),
        ('wash_timer_log.txt', b'Wash Protocol Log:\n14:30 - Started wash 1 (5 min)\n14:35 - Started wash 2 (5 min)\n14:40 - Started wash 3 (5 min)\n14:45 - Wash protocol complete\n'),
        ('fluorescence_data.csv', b'Cell_ID,Time_min,GFP_Intensity,Cell_Area\n1,0,120,850\n1,5,145,862\n1,10,168,875\n2,0,98,780\n2,5,134,795\n'),
        ('ms_parameters.txt', b'LC-MS/MS Parameters:\nLC Column: C18, 2.1x150mm, 1.7um\nGradient: 2-35% ACN over 120 min\nFlow Rate: 0.3 mL/min\nMS1 Resolution: 70,000\nMS2 Resolution: 17,500\n'),
        ('maxquant_log.txt', b'MaxQuant Processing Log:\nDatabase: UniProt Human (20,431 sequences)\nSearch Engine: Andromeda\nPeptide FDR: 1%\nProtein FDR: 1%\nTotal Peptides: 45,672\nUnique Peptides: 38,241\n'),
        ('acquisition_settings.txt', b'Time-lapse Settings:\nInterval: 5 minutes\nTotal Duration: 8 hours\nChannels: GFP, Phase\nExposure: 100ms GFP, 50ms Phase\nBinning: 1x1\n'),
        
        # PDF files (simplified)
        ('gel_analysis.pdf', b'%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\nfake_pdf_gel_densitometry_analysis'),
        ('statistics.pdf', b'%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\nfake_pdf_statistical_analysis_results'),
        ('calibration_report.pdf', b'%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\nfake_pdf_instrument_calibration_report'),
        ('lab_notebook_page1.pdf', b'%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\nfake_pdf_laboratory_notebook_scan'),
        ('mass_accuracy.pdf', b'%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\nfake_pdf_mass_accuracy_assessment'),
        ('dynamics_stats.pdf', b'%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\nfake_pdf_dynamics_statistical_analysis'),
        
        # Additional CSV files
        ('temp_log.csv', b'Time,Temperature_C,Location\n09:00,4.2,Cold_Room\n10:00,4.1,Cold_Room\n11:00,4.3,Cold_Room\n12:00,4.0,Cold_Room\n'),
        ('focus_drift.csv', b'Time_min,Z_Position_um,Drift_um\n0,100.0,0.0\n30,100.1,0.1\n60,100.3,0.3\n90,100.2,0.2\n120,100.4,0.4\n'),
        ('cell_tracks.csv', b'Track_ID,Time_min,X_pos,Y_pos,Area,Intensity\n1,0,150,200,850,1200\n1,5,152,198,862,1245\n1,10,155,195,875,1290\n'),
        ('lc_pressure_trace.csv', b'Time_min,Pressure_Bar,Solvent_A_percent,Solvent_B_percent\n0,180,98,2\n30,185,85,15\n60,190,70,30\n90,188,50,50\n120,185,35,65\n'),
        ('speedvac_log.txt', b'SpeedVac Concentration Log:\nStart Time: 14:30\nEnd Time: 16:30\nDuration: 2 hours\nInitial Volume: 2.0 mL\nFinal Volume: 0.2 mL\nConcentration Factor: 10x\n'),
        ('protocol_notes.txt', b'Protocol Optimization Notes:\n1. Increase lysis buffer volume by 20% for better yield\n2. Extend wash steps to 15 CV for higher purity\n3. Use 250mM imidazole for sharper elution\n4. Monitor temperature more closely\n'),
    ]
    
    for filename, content in files_to_create:
        filepath = os.path.join(ann_dir, filename)
        with open(filepath, 'wb') as f:
            f.write(content)
    
    print(f"Created {len(files_to_create)} media files in {ann_dir}")


def create_export_metadata():
    """Create comprehensive export metadata"""
    base_time = datetime(2025, 1, 1, 9, 0, 0)
    
    return {
        'export_timestamp': base_time.isoformat(),
        'source_user_id': 1,
        'source_username': 'dr_smith',
        'source_email': 'smith@lab.edu',
        'cupcake_version': '1.0',
        'export_format_version': '3.0',
        'archive_format': 'zip',
        'archive_sha256': 'mock_sha256_hash_for_test_fixture',
        'stats': {
            'protocols_exported': 5,
            'sessions_exported': 5,
            'annotations_exported': 78,
            'files_exported': 45,
            'instruments_exported': 6,
            'users_exported': 4,
            'projects_exported': 3,
            'lab_groups_exported': 2,
            'reagents_exported': 5,
            'storage_objects_exported': 3,
            'tags_exported': 5,
            'relationships_exported': 25
        },
        'export_summary': {
            'laboratory_name': 'Advanced Proteomics Research Lab',
            'export_purpose': 'Comprehensive test fixture for import system validation',
            'data_time_range': f"{base_time.isoformat()} to {(base_time + timedelta(days=5)).isoformat()}",
            'experimental_focus': [
                'Protein purification and characterization',
                'Western blot analysis',
                'Cell culture and transfection',
                'Mass spectrometry proteomics',
                'Live cell fluorescence microscopy'
            ],
            'annotation_type_distribution': {
                'text': 32,
                'image': 15,
                'file': 12,
                'video': 8,
                'table': 5,
                'other': 3,
                'audio': 1,
                'sketch': 1,
                'checklist': 1
            },
            'instruments_used': [
                'LC-MS/MS Orbitrap',
                'Fluorescence Microscope', 
                'PCR Thermocycler',
                'Protein Crystallization Robot',
                'Cell Culture Hood',
                'Spectrophotometer'
            ]
        }
    }


if __name__ == '__main__':
    create_complex_test_fixture()
    print("Complex test fixture creation completed!")
    print("Created test_fixture_zip.zip with:")
    print("- 5 comprehensive protocols with 51 detailed steps")
    print("- 5 experimental sessions")
    print("- 78 annotations across all annotation types")
    print("- 6 instruments with usage tracking")
    print("- 4 users with different roles")
    print("- 3 research projects")
    print("- 45 media files (images, videos, data files, PDFs)")
    print("- Comprehensive relationships and metadata")