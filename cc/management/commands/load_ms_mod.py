from django.core.management.base import BaseCommand
from cc.models import Unimod
import pronto
import requests
from io import BytesIO

def load_instrument():
    response = requests.get("https://www.unimod.org/obo/unimod.obo")
    raw_data = response.text

    # Manually parse the xrefs section
    xrefs_data = {}
    current_term = None
    for line in raw_data.splitlines():
        if line.startswith("[Term]"):
            current_term = None
        elif line.startswith("id: "):
            current_term = line.split("id: ")[1]
            xrefs_data[current_term] = []
        elif line.startswith("xref: ") and current_term:
            xref = line.split("xref: ")[1]
            xrefs_data[current_term].append(xref.replace("\"", ""))

    ms = pronto.Ontology(BytesIO(response.content))
    sub_0 = ms["UNIMOD:0"].subclasses().to_set()
    for term in sub_0:
        if term.is_leaf():
            existed_dict = {}
            for xref in xrefs_data.get(term.id, []):
                xref_id, xref_desc = xref.split(" ", 1)
                c = {"id": xref_id, "description": xref_desc}
                if xref_id not in existed_dict:
                    existed_dict[xref_id] = c
                else:
                    existed_dict[xref_id]["description"] = existed_dict[xref_id]["description"] + "," + c["description"]
            result = list(existed_dict.values())
            Unimod.objects.create(
                accession=term.id,
                name=term.name,
                definition = term.definition,
                additional_data = result
            )



class Command(BaseCommand):
    help = 'Load MS Modification data into the database.'

    def handle(self, *args, **options):
        Unimod.objects.all().delete()
        load_instrument()
