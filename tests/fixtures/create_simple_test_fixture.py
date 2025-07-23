#!/usr/bin/env python3
"""
Simple test fixture for testing import/export functionality
Creates basic data without complex JSON escaping issues
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


def create_simple_test_fixture():
    """Create simple test fixture with basic CUPCAKE models"""
    
    print("🔬 Creating simple CUPCAKE test fixture...")
    
    # Create temporary directory for building the archive
    temp_dir = tempfile.mkdtemp()
    
    try:
        # Create the SQLite database with test data
        sqlite_path = os.path.join(temp_dir, 'user_data.sqlite')
        print("📊 Creating database...")
        create_simple_database(sqlite_path)
        
        # Create media files directory structure
        media_dir = os.path.join(temp_dir, 'media')
        print("📁 Creating media files...")
        create_simple_media_files(media_dir)
        
        # Create export metadata
        print("📋 Generating export metadata...")
        metadata = create_simple_export_metadata()
        
        with open(os.path.join(temp_dir, 'export_metadata.json'), 'w') as f:
            json.dump(metadata, f, indent=2)
        
        # Create the ZIP archive
        archive_path = 'simple_test_fixture.zip'
        print("🗜️ Creating ZIP archive...")
        with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arc_path = os.path.relpath(file_path, temp_dir)
                    zipf.write(file_path, arc_path)
        
        print(f"✅ Created simple test fixture: {archive_path}")
        print_fixture_summary()
        return archive_path
        
    finally:
        shutil.rmtree(temp_dir)


def create_simple_database(sqlite_path):
    """Create SQLite database with basic CUPCAKE models"""
    conn = sqlite3.connect(sqlite_path)
    
    # Create basic tables
    create_basic_tables(conn)
    
    # Insert test data
    insert_basic_test_data(conn)
    
    conn.commit()
    conn.close()


def create_basic_tables(conn):
    """Create basic database tables"""
    
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
    
    # Lab groups table
    conn.execute('''
        CREATE TABLE export_lab_groups (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            created_at TEXT,
            updated_at TEXT,
            is_core_facility BOOLEAN DEFAULT 0
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
            FOREIGN KEY (owner_id) REFERENCES export_users (id)
        )
    ''')
    
    # Instruments table
    conn.execute('''
        CREATE TABLE export_instruments (
            id INTEGER PRIMARY KEY,
            instrument_name TEXT NOT NULL,
            instrument_description TEXT,
            location TEXT,
            manufacturer TEXT,
            model TEXT,
            is_active BOOLEAN DEFAULT 1
        )
    ''')
    
    # Instrument jobs table
    conn.execute('''
        CREATE TABLE export_instrument_jobs (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            instrument_id INTEGER,
            project_id INTEGER,
            sample_number INTEGER DEFAULT 1,
            cost_center TEXT,
            amount DECIMAL(10,2),
            job_type TEXT DEFAULT 'analysis',
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            FOREIGN KEY (user_id) REFERENCES export_users (id),
            FOREIGN KEY (instrument_id) REFERENCES export_instruments (id),
            FOREIGN KEY (project_id) REFERENCES export_projects (id)
        )
    ''')
    
    # Service tiers table
    conn.execute('''
        CREATE TABLE export_service_tiers (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            lab_group_id INTEGER,
            is_active BOOLEAN DEFAULT 1,
            created_at TEXT,
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
            created_at TEXT,
            FOREIGN KEY (service_tier_id) REFERENCES export_service_tiers (id),
            FOREIGN KEY (instrument_id) REFERENCES export_instruments (id)
        )
    ''')
    
    # Backup logs table
    conn.execute('''
        CREATE TABLE export_backup_logs (
            id INTEGER PRIMARY KEY,
            backup_type TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            duration_seconds INTEGER,
            file_size_bytes INTEGER,
            success_message TEXT,
            error_message TEXT
        )
    ''')
    
    # Sample pools table
    conn.execute('''
        CREATE TABLE export_sample_pools (
            id INTEGER PRIMARY KEY,
            instrument_job_id INTEGER,
            pool_name TEXT NOT NULL,
            pool_description TEXT,
            created_by_id INTEGER,
            created_at TEXT,
            pooled_only_samples TEXT,
            pooled_and_independent_samples TEXT,
            FOREIGN KEY (instrument_job_id) REFERENCES export_instrument_jobs (id),
            FOREIGN KEY (created_by_id) REFERENCES export_users (id)
        )
    ''')
    
    # Cell types table
    conn.execute('''
        CREATE TABLE export_cell_types (
            id INTEGER PRIMARY KEY,
            identifier TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            synonyms TEXT,
            is_obsolete BOOLEAN DEFAULT 0
        )
    ''')
    
    # Annotations table
    conn.execute('''
        CREATE TABLE export_annotations (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            annotation_type TEXT,
            annotation_name TEXT,
            annotation_data TEXT,
            created_at TEXT,
            file_size INTEGER,
            FOREIGN KEY (user_id) REFERENCES export_users (id)
        )
    ''')


def insert_basic_test_data(conn):
    """Insert basic test data"""
    
    # Insert users
    users = [
        (1, 'dr_sarah_johnson', 'sarah.johnson@university.edu', 'Sarah', 'Johnson', True, True, '2023-01-15T09:00:00'),
        (2, 'prof_michael_chen', 'michael.chen@university.edu', 'Michael', 'Chen', True, True, '2023-01-10T08:30:00'),
        (3, 'lab_tech_maria', 'maria.garcia@university.edu', 'Maria', 'Garcia', False, True, '2023-02-01T10:00:00')
    ]
    
    for user in users:
        conn.execute('''
            INSERT INTO export_users (id, username, email, first_name, last_name, 
                                    is_staff, is_active, date_joined)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', user)
    
    # Insert lab groups
    lab_groups = [
        (1, 'Proteomics Core Facility', 'Mass spectrometry core facility', '2023-01-01T00:00:00', '2023-01-01T00:00:00', True),
        (2, 'Johnson Biochemistry Lab', 'Research lab for protein studies', '2023-01-01T00:00:00', '2023-01-01T00:00:00', False)
    ]
    
    for group in lab_groups:
        conn.execute('''
            INSERT INTO export_lab_groups (id, name, description, created_at, updated_at, is_core_facility)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', group)
    
    # Insert projects
    projects = [
        (1, 'Alzheimer Biomarker Study', 'Proteomic analysis of AD biomarkers', 1, '2023-03-01T00:00:00', '2023-03-01T00:00:00'),
        (2, 'Cancer Cell Analysis', 'Proteome profiling of cancer cells', 2, '2023-02-15T00:00:00', '2023-02-15T00:00:00')
    ]
    
    for project in projects:
        conn.execute('''
            INSERT INTO export_projects (id, project_name, project_description, owner_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', project)
    
    # Insert instruments
    instruments = [
        (1, 'Orbitrap Fusion Lumos', 'High-resolution mass spectrometer', 'Room 401A', 'Thermo Fisher', 'Orbitrap Fusion Lumos', True),
        (2, 'Q Exactive Plus', 'Benchtop mass spectrometer', 'Room 401B', 'Thermo Fisher', 'Q Exactive Plus', True)
    ]
    
    for instrument in instruments:
        conn.execute('''
            INSERT INTO export_instruments (id, instrument_name, instrument_description, location, 
                                          manufacturer, model, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', instrument)
    
    # Insert instrument jobs
    jobs = [
        (1, 1, 1, 1, 24, 'CC-1001', 1200.00, 'analysis', 'completed', '2023-07-01T10:00:00'),
        (2, 2, 2, 2, 12, 'CC-1002', 800.00, 'analysis', 'running', '2023-07-15T14:30:00'),
        (3, 3, 1, 1, 6, 'CC-1003', 400.00, 'quality_control', 'pending', '2023-07-20T09:15:00')
    ]
    
    for job in jobs:
        conn.execute('''
            INSERT INTO export_instrument_jobs (id, user_id, instrument_id, project_id, sample_number,
                                               cost_center, amount, job_type, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', job)
    
    # Insert service tiers
    tiers = [
        (1, 'Academic Standard', 'Standard academic pricing', 1, True, '2023-01-01T00:00:00'),
        (2, 'Commercial Rate', 'Commercial pricing for industry', 1, True, '2023-01-01T00:00:00')
    ]
    
    for tier in tiers:
        conn.execute('''
            INSERT INTO export_service_tiers (id, name, description, lab_group_id, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', tier)
    
    # Insert service prices
    prices = [
        (1, 1, 1, 'per_hour_instrument', 125.00, 'USD', '2023-01-01T00:00:00'),
        (2, 1, 2, 'per_hour_instrument', 95.00, 'USD', '2023-01-01T00:00:00'),
        (3, 2, 1, 'per_hour_instrument', 250.00, 'USD', '2023-01-01T00:00:00')
    ]
    
    for price in prices:
        conn.execute('''
            INSERT INTO export_service_prices (id, service_tier_id, instrument_id, billing_unit, 
                                             price, currency, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', price)
    
    # Insert backup logs
    backups = [
        (1, 'database', 'completed', '2023-07-20T02:00:00', '2023-07-20T02:15:00', 900, 1048576000, 'Database backup completed successfully', None),
        (2, 'media_files', 'completed', '2023-07-20T03:00:00', '2023-07-20T03:45:00', 2700, 5242880000, 'Media files backup completed', None),
        (3, 'database', 'failed', '2023-07-21T02:00:00', '2023-07-21T02:05:00', 300, None, None, 'Insufficient disk space')
    ]
    
    for backup in backups:
        conn.execute('''
            INSERT INTO export_backup_logs (id, backup_type, status, started_at, completed_at,
                                          duration_seconds, file_size_bytes, success_message, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', backup)
    
    # Insert sample pools
    pools = [
        (1, 1, 'QC_Pool_01', 'Quality control pool for batch 1', 1, '2023-07-01T11:00:00', '[1, 2, 3, 4]', '[5, 6]'),
        (2, 2, 'Bio_Pool_01', 'Biological replicate pool', 2, '2023-07-15T15:00:00', '[1, 3, 5]', '[2, 4]')
    ]
    
    for pool in pools:
        conn.execute('''
            INSERT INTO export_sample_pools (id, instrument_job_id, pool_name, pool_description,
                                           created_by_id, created_at, pooled_only_samples,
                                           pooled_and_independent_samples)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', pool)
    
    # Insert cell types
    cell_types = [
        (1, 'CL:0000066', 'epithelial cell', 'A cell that is usually found in a two-dimensional sheet', '["epithelial cells", "epitheliocyte"]', False),
        (2, 'CL:0000084', 'T cell', 'A type of lymphocyte with T cell receptor complex', '["T lymphocyte", "T-cell"]', False),
        (3, 'CL:0000236', 'B cell', 'A lymphocyte of B lineage capable of B cell mediated immunity', '["B lymphocyte", "B-cell"]', False)
    ]
    
    for cell_type in cell_types:
        conn.execute('''
            INSERT INTO export_cell_types (id, identifier, name, description, synonyms, is_obsolete)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', cell_type)
    
    # Insert annotations
    annotations = [
        (1, 1, 'text_note', 'Sample prep note', 'Sample preparation went smoothly, no issues observed', '2023-07-01T10:30:00', 52),
        (2, 2, 'voice_note', 'Protocol modification', 'audio_recordings/protocol_mod_001.wav', '2023-07-15T14:45:00', 2048000),
        (3, 1, 'image', 'Gel result', 'images/gel_result_batch1.jpg', '2023-07-01T16:00:00', 1024000),
        (4, 3, 'text_note', 'QC observation', 'Excellent protein yield observed in this batch', '2023-07-20T09:30:00', 45)
    ]
    
    for annotation in annotations:
        conn.execute('''
            INSERT INTO export_annotations (id, user_id, annotation_type, annotation_name, 
                                          annotation_data, created_at, file_size)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', annotation)


def create_simple_media_files(media_dir):
    """Create simple media file structure"""
    
    os.makedirs(media_dir, exist_ok=True)
    
    # Create subdirectories
    subdirs = ['audio_recordings', 'images', 'documents']
    for subdir in subdirs:
        os.makedirs(os.path.join(media_dir, subdir), exist_ok=True)
    
    # Create a sample audio file
    audio_file = os.path.join(media_dir, 'audio_recordings', 'protocol_mod_001.wav')
    with open(audio_file, 'wb') as f:
        f.write(b'RIFF\x24\x08\x00\x00WAVEfmt ')  # WAV header
        f.write(os.urandom(2048))  # Sample audio data
    
    # Create a sample image file
    image_file = os.path.join(media_dir, 'images', 'gel_result_batch1.jpg')
    with open(image_file, 'wb') as f:
        f.write(b'\xff\xd8\xff\xe0\x00\x10JFIF')  # JPEG header
        f.write(os.urandom(1024))  # Sample image data
    
    # Create a sample document
    doc_file = os.path.join(media_dir, 'documents', 'protocol_supplement.pdf')
    with open(doc_file, 'wb') as f:
        f.write(b'%PDF-1.4\n')  # PDF header
        f.write(os.urandom(512))  # Sample PDF data


def create_simple_export_metadata():
    """Create simple export metadata"""
    
    return {
        'export_info': {
            'version': '1.0',
            'created_at': datetime.now().isoformat(),
            'created_by': 'CUPCAKE Test System',
            'cupcake_version': '2.5.0',
            'fixture_type': 'simple_test_data'
        },
        'data_summary': {
            'total_users': 3,
            'total_lab_groups': 2,
            'total_projects': 2,
            'total_instruments': 2,
            'total_instrument_jobs': 3,
            'total_service_tiers': 2,
            'total_backup_logs': 3,
            'total_sample_pools': 2,
            'total_cell_types': 3,
            'total_annotations': 4,
            'media_files_count': 3
        },
        'model_coverage': [
            'User', 'LabGroup', 'Project', 'Instrument', 'InstrumentJob',
            'ServiceTier', 'ServicePrice', 'BackupLog', 'SamplePool',
            'CellType', 'Annotation'
        ],
        'testing_scenarios': [
            'Basic laboratory environment',
            'Simple instrument jobs',
            'Basic billing structure',
            'Sample pooling workflows', 
            'Backup monitoring',
            'Basic ontology data',
            'Media file handling'
        ]
    }


def print_fixture_summary():
    """Print summary of created fixture"""
    
    print("\n📋 **SIMPLE TEST FIXTURE SUMMARY**")
    print("=" * 40)
    print("👥 Users: 3")
    print("🏢 Lab Groups: 2")  
    print("📊 Projects: 2")
    print("🔬 Instruments: 2")
    print("⚗️  Instrument Jobs: 3")
    print("💰 Service Tiers: 2")
    print("💾 Backup Logs: 3")
    print("🧬 Sample Pools: 2")
    print("🔬 Cell Types: 3")
    print("📝 Annotations: 4")
    print("📁 Media Files: 3")
    print("=" * 40)
    print("✅ Ready for import/export testing!")


if __name__ == '__main__':
    create_simple_test_fixture()