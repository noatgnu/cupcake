import json
import requests
from django.conf import settings
import re

default_columns = [{
            "name": "Source name", "type": "", "mandatory": True
        },
            {
            "name": "Organism", "type": "Characteristics", "mandatory": True
        }, {
            "name": "Tissue", "type": "Characteristics", "mandatory": True
        }, {
            "name": "Disease", "type": "Characteristics", "mandatory": True
        }, {
            "name": "Cell type", "type": "Characteristics", "mandatory": True
        }, {
            "name": "Biological replicate", "type": "Characteristics", "mandatory": True
        },{
            "name": "Material type", "type": "", "mandatory": True
        },
            {
                "name": "Assay name", "type": "", "mandatory": True
        }, {
            "name": "Technology type", "type": "", "mandatory": True
        },  {
                "name": "Technical replicate", "type": "Comment", "mandatory": True
            },
            {"name": "Label", "type": "Comment", "mandatory": True},
            {"name": "Fraction identifier", "type": "Comment", "mandatory": True},
            {"name": "Instrument", "type": "Comment", "mandatory": True},
            {"name": "Data file", "type": "Comment", "mandatory": True},
            {"name": "Cleavage agent details", "type": "Comment", "mandatory": True},
            {"name": "Modification parameters", "type": "Comment", "mandatory": True},
            {"name": "Dissociation method", "type": "Comment", "mandatory": True},
            {"name": "Precursor mass tolerance", "type": "Comment", "mandatory": True},
            {"name": "Fragment mass tolerance", "type": "Comment", "mandatory": True},
        ]

user_metadata = [
            {
                "name": "Source name", "type": "", "mandatory": True
            },
            {
                "name": "Organism", "type": "Characteristics", "mandatory": True
            },
        {
            "name": "Disease", "type": "Characteristics", "mandatory": True
        },
            {
                "name": "Tissue", "type": "Characteristics", "mandatory": True
            },
            {
                "name": "Cell type", "type": "Characteristics", "mandatory": False
            },
            {
                "name": "Reduction reagent", "type": "Comment", "mandatory": False
            }
            ,
            {
                "name": "Alkylation reagent", "type": "Comment", "mandatory": False
            },
{
        "name": "Sex", "type": "Characteristics", "mandatory": False
    },
    {
        "name": "Developmental stage", "type": "Characteristics", "mandatory": False
    },
    {
        "name": "Age", "type": "Characteristics", "mandatory": False
    },
{
      "name": "Mass", "type": "Characteristics","mandatory": True, "value": "0 ng"
    },
            {
              "name": "Assay name", "type": "", "mandatory": True, "value": "run 1", "hidden": True, "auto_generated": True
            },
            {
                "name": "Technology type", "type": "", "mandatory": True, "value": "proteomic profiling by mass spectrometry", "hidden": True
            },
            {
                "name": "Technical replicate", "type": "Comment", "mandatory": True, "value": "1"
            },
            {
                "name": "Biological replicate", "type": "Characteristics", "mandatory": True, "value": "1"
            }
            ,
            {
                "name": "Sample type", "type": "Characteristics", "mandatory": True
            },
            {
                "name": "Enrichment process", "type": "Characteristics", "mandatory": True
            }
            ,
            {
                "name": "Cleavage agent details", "type": "Comment", "mandatory": True
            },


    {
        "name": "Modification parameters", "type": "Comment", "mandatory": True
    }

        ]

staff_metadata = [
            {
                "name": "Data file", "type": "Comment", "mandatory": True
            },
            {
                "name": "File uri", "type": "Comment", "mandatory": False, "hidden": True, "value": "not available"
            },
            {
                "name": "Proteomics data acquisition method", "type": "Comment", "mandatory": True
            }
            ,
            {
                "name": "Label",
                "type": "Comment",
                "mandatory": True,

            },
    {
        "name": "Fraction identifier", "type": "Comment", "mandatory": True, "value": "1",
                "hidden": True
    },
            {
                "name": "MS1 scan range", "type": "Comment", "mandatory": True
            },
{
        "name": "Instrument", "type": "Comment", "mandatory": True, "hidden": True
    },
            {
                "name": "MS2 analyzer type", "type": "Comment", "mandatory": True, "hidden": True
            },
    {
      "name": "Position", "type": "Comment", "mandatory": True
    },

    {"name": "Dissociation method", "type": "Comment", "mandatory": True},
    {"name": "Precursor mass tolerance", "type": "Comment", "mandatory": True, "value": "0 ppm"},
    {"name": "Fragment mass tolerance", "type": "Comment", "mandatory": True, "value": "0 Da"},
        ]

required_metadata = [
    "source name",
    "characteristics[organism]",
    "characteristics[disease]",
    "characteristics[organism part]",
    "characteristics[cell type]",
    "assay name",
    "comment[fraction identifier]",
    "comment[label]",
    "comment[instrument]",
    "comment[technical replicate]",
    "characteristics[biological replicate]",
    "comment[cleavage agent details]",
    "comment[data file]"
    "technology type",
]

required_metadata_name = [
    "source name",
    "organism",
    "disease",
    "organism part",
    "cell type",
    "assay name",
    "fraction identifier",
    "label",
    "instrument",
    "technical replicate",
    "biological replicate",
    "cleavage agent details",
]


def send_slack_notification(message, channel=None, username=None, icon_emoji=None, attachments=None):
    """
    Send a notification message to Slack channel

    Args:
        message: The message text
        channel: Optional channel override
        username: Display name for the bot
        icon_emoji: Emoji to use as the icon
        attachments: Any Slack message attachments
    """
    webhook_url = getattr(settings, 'SLACK_WEBHOOK_URL', None)
    if not webhook_url:
        return False

    payload = {'text': message}

    if channel:
        payload['channel'] = channel
    if username:
        payload['username'] = username
    if icon_emoji:
        payload['icon_emoji'] = icon_emoji
    if attachments:
        payload['attachments'] = attachments

    response = requests.post(
        webhook_url,
        data=json.dumps(payload),
        headers={'Content-Type': 'application/json'}
    )

    return response.status_code == 200




def identify_barcode_format(barcode):
    """
    Attempt to identify the barcode format from a string

    Args:
        barcode (str): The barcode string

    Returns:
        str: The identified barcode format or "Unknown"
    """
    if not barcode or not isinstance(barcode, str):
        return "Invalid"

    barcode = barcode.strip()
    length = len(barcode)
    is_numeric = barcode.isdigit()

    if is_numeric:
        if length == 8:
            if barcode[0] == '0':
                return "UPC-E"
            return "EAN-8"
        elif length == 12:
            return "UPC-A"
        elif length == 13:
            if barcode.startswith(('978', '979')):
                return "ISBN-13"
            return "EAN-13"
        elif length == 14:
            return "GTIN-14"

    if re.match(r'^[A-Z0-9\-\.\/\+\%\$\s]+$', barcode):
        return "Code 39"

    if any(c.isalpha() for c in barcode) and any(c.isdigit() for c in barcode):
        return "Code 128"

    if re.search(r'\(\d{2,4}\)', barcode):
        return "GS1-128"

    if re.match(r'^https?://', barcode) or length > 30:
        return "2D Barcode (QR/DataMatrix)"

    if re.match(r'^[A-Z]{2,3}-\d+$', barcode):
        return "Lab Format"

    return "Unknown"

def get_all_template():
    try:
        from sdrf_pipelines.sdrf.sdrf_schema import ALL_TEMPLATES
        return ALL_TEMPLATES
    except ImportError:
        pass

