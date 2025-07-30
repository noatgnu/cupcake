#!/usr/bin/env python3
"""
Generate GitHub release notes with ontology statistics and package information.
This script should be run after the Pi image build is complete.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

def load_json_file(filepath):
    """Load JSON file with error handling."""
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Warning: {filepath} not found")
        return {}
    except json.JSONDecodeError:
        print(f"Warning: Invalid JSON in {filepath}")
        return {}

def format_number(num):
    """Format number with commas."""
    return f"{num:,}"

def generate_release_notes(release_info_dir="/opt/cupcake/release-info"):
    """Generate comprehensive release notes."""
    
    # Load all information files
    ontology_stats = load_json_file(f"{release_info_dir}/ontology_statistics.json")
    package_licenses = load_json_file(f"{release_info_dir}/package_licenses.json")
    installed_packages = load_json_file(f"{release_info_dir}/installed_packages.json")
    release_info = load_json_file(f"{release_info_dir}/release_info.json")
    
    # Generate release notes
    notes = []
    
    # Header
    notes.append("# CUPCAKE Raspberry Pi ARM64 Image")
    notes.append("")
    notes.append("This is an official ARM64 Raspberry Pi image for CUPCAKE with pre-loaded ontology databases.")
    notes.append("")
    
    # Build Information
    if release_info:
        build_date = release_info.get('build_date', 'Unknown')
        if build_date != 'Unknown':
            try:
                build_date = datetime.fromisoformat(build_date.replace('Z', '+00:00')).strftime('%Y-%m-%d %H:%M:%S UTC')
            except:
                pass
        
        notes.append("## Build Information")
        notes.append("")
        notes.append(f"- **Build Date**: {build_date}")
        notes.append(f"- **Architecture**: {release_info.get('system_info', {}).get('architecture', 'ARM64 (aarch64)')}")
        notes.append(f"- **Target Platform**: {release_info.get('system_info', {}).get('target_platform', 'Raspberry Pi 4/5')}")
        notes.append(f"- **Python Version**: {release_info.get('system_info', {}).get('python_version', '3.11')}")
        notes.append(f"- **Django Version**: {release_info.get('system_info', {}).get('django_version', 'Unknown')}")
        notes.append("")
    
    # Ontology Databases
    if ontology_stats.get('ontology_statistics'):
        total_records = ontology_stats.get('total_records', 0)
        notes.append("## Pre-loaded Ontology Databases")
        notes.append("")
        notes.append(f"This image includes **{format_number(total_records)} ontology records** from the following databases:")
        notes.append("")
        
        ontologies = ontology_stats['ontology_statistics']
        for name, count in ontologies.items():
            display_name = name.replace('_', ' ')
            notes.append(f"- **{display_name}**: {format_number(count)} records")
        
        notes.append("")
        notes.append("### Ontology Sources")
        notes.append("")
        notes.append("- **MONDO Disease Ontology**: Comprehensive disease classification")
        notes.append("- **UBERON Anatomy**: Anatomical structures and tissues")
        notes.append("- **NCBI Taxonomy**: Species and organism classification")
        notes.append("- **ChEBI Compounds**: Chemical compounds (proteomics-filtered)")
        notes.append("- **PSI-MS Ontology**: Mass spectrometry instruments and methods")
        notes.append("- **UniProt Species**: Controlled vocabulary for species")
        notes.append("- **UniMod Modifications**: Protein modifications for mass spectrometry")
        notes.append("- **UniProt Tissues**: Tissue and organ terminology")
        notes.append("- **UniProt Human Diseases**: Human disease classifications")
        notes.append("- **MS Unique Vocabularies**: MS instruments, methods, and reagents")
        notes.append("- **Subcellular Locations**: Cellular compartments and locations")
        notes.append("- **Cell Types**: Cell ontology and cell line information")
        notes.append("")
    
    # Installation Instructions
    notes.append("## Installation")
    notes.append("")
    notes.append("1. Download the image file")
    notes.append("2. Flash to SD card (32GB+ recommended) using Raspberry Pi Imager or similar tool")
    notes.append("3. Boot your Raspberry Pi 4 or 5")
    notes.append("4. Access CUPCAKE at `http://your-pi-ip:8000`")
    notes.append("5. Default login: `admin` / `cupcake123`")
    notes.append("")
    
    # System Requirements
    notes.append("## System Requirements")
    notes.append("")
    notes.append("- **Raspberry Pi 4 or 5** (4GB+ RAM recommended)")
    notes.append("- **32GB+ SD card** (for ontology databases)")
    notes.append("- **Network connection** for initial setup")
    notes.append("")
    
    # Services
    notes.append("## Included Services")
    notes.append("")
    notes.append("- **CUPCAKE Web Server**: Main application (port 8000)")
    notes.append("- **PostgreSQL 15**: Database server (port 5432)")
    notes.append("- **Redis**: Caching and task queue (port 6379)")
    notes.append("- **Background Workers**: For processing tasks")
    notes.append("- **Nginx**: Reverse proxy (if configured)")
    notes.append("")
    
    # Package Information
    if release_info.get('python_packages'):
        total_packages = release_info['python_packages'].get('total_packages', 0)
        notes.append("## Python Dependencies")
        notes.append("")
        notes.append(f"This image includes **{total_packages} Python packages**. ")
        notes.append("See the attached license files for complete package and license information.")
        notes.append("")
    
    # Files Included
    notes.append("## Release Files")
    notes.append("")
    notes.append("- **cupcake-pi-arm64.img.xz**: Compressed Raspberry Pi image")
    notes.append("- **ontology_statistics.json**: Detailed ontology database statistics")
    notes.append("- **package_licenses.json**: Complete package license information (JSON)")
    notes.append("- **package_licenses.txt**: Complete package license information (text)")
    notes.append("- **installed_packages.json**: List of all installed Python packages (JSON)")
    notes.append("- **installed_packages.txt**: List of all installed Python packages (text)")
    notes.append("- **release_info.json**: Comprehensive build and system information")
    notes.append("")
    
    # Usage Notes
    notes.append("## Usage Notes")
    notes.append("")
    notes.append("- All ontology databases are pre-loaded and ready to use")
    notes.append("- ChEBI compounds are filtered for proteomics relevance")
    notes.append("- Services start automatically on boot")
    notes.append("- SSH is enabled by default (change default passwords!)")
    notes.append("- System timezone is UTC (change as needed)")
    notes.append("")
    
    # Security Notice
    notes.append("## Security Notice")
    notes.append("")
    notes.append("⚠️ **Important**: This image uses default passwords and configurations suitable for development/testing.")
    notes.append("For production use:")
    notes.append("- Change default passwords immediately")
    notes.append("- Configure proper firewall rules")
    notes.append("- Enable HTTPS/SSL certificates")
    notes.append("- Review and harden security settings")
    notes.append("")
    
    # Support
    notes.append("## Support")
    notes.append("")
    notes.append("- **Documentation**: [CUPCAKE Documentation](https://github.com/noatgnu/cupcake)")
    notes.append("- **Issues**: [GitHub Issues](https://github.com/noatgnu/cupcake/issues)")
    notes.append("- **License**: MIT License")
    notes.append("")
    
    # Footer
    notes.append("---")
    notes.append("")
    notes.append("Built with 🧁 by the CUPCAKE team")
    
    return "\n".join(notes)

def main():
    """Main function."""
    if len(sys.argv) > 1:
        release_info_dir = sys.argv[1]
    else:
        release_info_dir = "/opt/cupcake/release-info"
    
    if not os.path.exists(release_info_dir):
        print(f"Error: Release info directory not found: {release_info_dir}")
        sys.exit(1)
    
    # Generate release notes
    release_notes = generate_release_notes(release_info_dir)
    
    # Save to file
    output_file = f"{release_info_dir}/release_notes.md"
    with open(output_file, 'w') as f:
        f.write(release_notes)
    
    print(f"Release notes generated: {output_file}")
    print("\n" + "="*50)
    print(release_notes)

if __name__ == "__main__":
    main()