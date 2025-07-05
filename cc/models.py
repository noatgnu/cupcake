from datetime import datetime, timedelta
import hashlib
import requests
from bs4 import BeautifulSoup
from django.core import signing
from django.db import models, transaction
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from rest_framework.authtoken.models import Token
from cc.utils import default_columns
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from simple_history.models import HistoricalRecords


# Create your models here.


class ImportTracker(models.Model):
    """Track user data imports for rollback functionality"""
    import_id = models.UUIDField(unique=True, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="import_trackers")
    import_started_at = models.DateTimeField(auto_now_add=True)
    import_completed_at = models.DateTimeField(blank=True, null=True)
    import_status = models.CharField(max_length=50, choices=[
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('reverted', 'Reverted')
    ], default='in_progress')
    archive_path = models.TextField()
    archive_size_mb = models.FloatField(blank=True, null=True)
    import_options = models.JSONField(default=dict)
    metadata = models.JSONField(default=dict)
    
    # Statistics
    total_objects_created = models.IntegerField(default=0)
    total_files_imported = models.IntegerField(default=0)
    total_relationships_created = models.IntegerField(default=0)
    
    # Rollback info
    can_revert = models.BooleanField(default=True)
    revert_reason = models.TextField(blank=True, null=True)
    reverted_at = models.DateTimeField(blank=True, null=True)
    reverted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, 
                                   related_name="reverted_imports", blank=True, null=True)
    
    class Meta:
        app_label = "cc"
        ordering = ["-import_started_at"]
        
    def __str__(self):
        return f"Import {self.import_id} - {self.user.username} - {self.import_status}"


class ImportedObject(models.Model):
    """Track individual objects created during import"""
    import_tracker = models.ForeignKey(ImportTracker, on_delete=models.CASCADE, related_name="imported_objects")
    model_name = models.CharField(max_length=100)
    object_id = models.IntegerField()
    original_id = models.IntegerField(blank=True, null=True)  # Original ID from export
    object_data = models.JSONField(default=dict)  # Store object data for rollback
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        app_label = "cc"
        unique_together = ['import_tracker', 'model_name', 'object_id']
        ordering = ["created_at"]
        
    def __str__(self):
        return f"{self.model_name}({self.object_id}) from import {self.import_tracker.import_id}"


class ImportedFile(models.Model):
    """Track files imported during import"""
    import_tracker = models.ForeignKey(ImportTracker, on_delete=models.CASCADE, related_name="imported_files")
    file_path = models.TextField()
    original_name = models.CharField(max_length=255)
    file_size_bytes = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        app_label = "cc"
        ordering = ["created_at"]
        
    def __str__(self):
        return f"File {self.original_name} from import {self.import_tracker.import_id}"


class ImportedRelationship(models.Model):
    """Track many-to-many relationships created during import"""
    import_tracker = models.ForeignKey(ImportTracker, on_delete=models.CASCADE, related_name="imported_relationships")
    from_model = models.CharField(max_length=100)
    from_object_id = models.IntegerField()
    to_model = models.CharField(max_length=100)
    to_object_id = models.IntegerField()
    relationship_field = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        app_label = "cc"
        ordering = ["created_at"]
        
    def __str__(self):
        return f"{self.from_model}({self.from_object_id}) -> {self.to_model}({self.to_object_id})"

class Project(models.Model):
    history = HistoricalRecords()
    project_name = models.CharField(max_length=255)
    project_description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remote_id = models.BigIntegerField(blank=True, null=True)
    sessions = models.ManyToManyField("Session", related_name="projects", blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="projects", blank=True, null=True)
    remote_host = models.ForeignKey("RemoteHost", on_delete=models.CASCADE, related_name="projects", blank=True, null=True)


    class Meta:
        app_label = "cc"
        ordering = ["id"]

    def __str__(self):
        return self.project_name

    def __repr__(self):
        return self.project_name

    def delete(self, using=None, keep_parents=False):
        super(Project, self).delete(using=using, keep_parents=keep_parents)

class ProtocolRating(models.Model):
    history = HistoricalRecords()
    protocol = models.ForeignKey("ProtocolModel", on_delete=models.CASCADE, related_name="ratings")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ratings")
    complexity_rating = models.IntegerField(blank=False, null=False, default=0)
    duration_rating = models.IntegerField(blank=False, null=False, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remote_id = models.BigIntegerField(blank=True, null=True)
    remote_host = models.ForeignKey("RemoteHost", on_delete=models.CASCADE, related_name="protocol_ratings", blank=True, null=True)

    class Meta:
        app_label = "cc"
        ordering = ["id"]

    def __str__(self):
        return f"{self.protocol} - {self.user} - {self.complexity_rating}"

    def __repr__(self):
        return f"{self.protocol} - {self.user} - {self.complexity_rating}"

    def save(self, *args, **kwargs):
        if self.complexity_rating < 0 or self.complexity_rating > 10:
            raise ValueError("Rating must be between 0 and 10")
        if self.duration_rating < 0 or self.duration_rating > 10:
            raise ValueError("Rating must be between 0 and 10")
        super().save(*args, **kwargs)


class ProtocolModel(models.Model):
    history = HistoricalRecords()
    protocol_id = models.BigIntegerField(blank=True, null=True)
    protocol_created_on = models.DateTimeField(blank=False, null=False, auto_now=True)
    protocol_doi = models.TextField(blank=True, null=True)
    protocol_title = models.TextField(blank=False, null=False)
    protocol_url = models.TextField(blank=True, null=True)
    protocol_version_uri = models.TextField(blank=True, null=True)
    protocol_description = models.TextField(blank=True, null=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="protocols", blank=True, null=True)
    enabled = models.BooleanField(default=False)
    editors = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="editor_protocols", blank=True)
    viewers = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="viewer_protocols", blank=True)
    remote_id = models.BigIntegerField(blank=True, null=True)
    model_hash = models.TextField(blank=True, null=True)
    remote_host = models.ForeignKey("RemoteHost", on_delete=models.CASCADE, related_name="protocols", blank=True, null=True)

    @staticmethod
    def create_protocol_from_url(url):
        initial_start = requests.get(url)
        # get url from meta tag using beautifulsoup
        soup = BeautifulSoup(initial_start.content, 'html.parser')
        meta = soup.find_all('meta')
        for tag in meta:
            if tag.get('property', None) == 'og:url':
                url = tag.get('content', None)
                break
        if not url:
            raise ValueError("Could not find protocol.io url")
        #if ProtocolModel.objects.filter(protocol_url=url).exists():
        #    return ProtocolModel.objects.get(protocol_url=url)
        # get protocol.io id from url
        protocol_meta = requests.get(f"https://www.protocols.io/api/v3/protocols/{url.split('/')[-1]}", headers={
            "Authorization": f"Bearer {settings.PROTOCOLS_IO_ACCESS_TOKEN}"
        })

        if protocol_meta.status_code == 200:
            protocol_meta = protocol_meta.json()
            if protocol_meta:
                with transaction.atomic():
                    sections_dict = {}
                    protocol = ProtocolModel()
                    protocol.protocol_id = protocol_meta["protocol"]["id"]
                    # convert unix timestamp to datetime
                    protocol.protocol_created_on = datetime.fromtimestamp(protocol_meta["protocol"]["created_on"])
                    protocol.protocol_doi = protocol_meta["protocol"]["doi"]
                    protocol.protocol_title = protocol_meta["protocol"]["title"]
                    protocol.protocol_description = protocol_meta["protocol"]["description"]
                    protocol.protocol_url = url
                    protocol.protocol_version_uri = protocol_meta["protocol"]["version_uri"]
                    protocol.save()

                    for step in protocol_meta["protocol"]["steps"]:
                        protocol_step = ProtocolStep()
                        for c in step["components"]:
                            if c["title"] == "Section":
                                if c["source"]["title"] not in sections_dict:
                                    section = ProtocolSection()
                                    section.protocol = protocol
                                    section.section_description = c["source"]["title"]
                                    section.section_duration = step["section_duration"]
                                    section.save()
                                    sections_dict[c["source"]["title"]] = section
                                protocol_step.step_section = sections_dict[c["source"]["title"]]

                            elif c["title"] == "description":
                                protocol_step.step_description = c["source"]["description"]
                        protocol_step.protocol = protocol
                        protocol_step.step_id = step["id"]
                        protocol_step.step_duration = step["duration"]
                        protocol_step.save()
                with transaction.atomic():
                    for step in protocol_meta["protocol"]["steps"]:
                        protocol_step = protocol.steps.get(step_id=step["id"])
                        if step["previous_id"] != 0:
                            protocol_step.previous_step = protocol.steps.get(step_id=step["previous_id"])

                        protocol_step.save()
                return protocol
        else:
            raise ValueError(f"Could not find protocol.io protocol with url {url}")

    def calculate_protocol_hash(self):
        """
        calculate sha256 hash of the protocol including protocol title, description, steps and sections
        :return:
        """

        hash_object = hashlib.sha256()
        if self.protocol_title:
            hash_object.update(self.protocol_title.encode())
        if self.protocol_description:
            hash_object.update(self.protocol_description.encode())
        for step in self.steps.all():
            if step.step_description:
                hash_object.update(step.step_description.encode())
            if step.step_duration:
                hash_object.update(str(step.step_duration).encode())
            if step.step_section:
                if step.step_section.section_description:
                    hash_object.update(step.step_section.section_description.encode())
                if step.step_section.section_duration:
                    hash_object.update(str(step.step_section.section_duration).encode())
        return hash_object.hexdigest()

    def save(self, *args, **kwargs):
        if self.id:
            self.model_hash = self.calculate_protocol_hash()
        super().save(*args, **kwargs)


    class Meta:
        app_label = "cc"
        ordering = ["protocol_id"]

    def __str__(self):
        return self.protocol_title

    def __repr__(self):
        return self.protocol_title

    @property
    def is_imported(self):
        """Check if this protocol was imported from another system"""
        return self.protocol_title and '[IMPORTED]' in self.protocol_title

    @property
    def import_source_info(self):
        """Get information about the import source"""
        try:
            imported_obj = ImportedObject.objects.filter(
                model_name='ProtocolModel',
                object_id=self.pk
            ).first()
            if imported_obj:
                return {
                    'import_tracker': imported_obj.import_tracker,
                    'original_id': imported_obj.original_id,
                    'imported_at': imported_obj.created_at
                }
        except:
            pass
        return None

    def get_first_in_protocol(self):
        step_list = self.steps.all()
        if step_list:
            for i in step_list:
                if not i.previous_step:
                    return i
                else:
                    if i.previous_step not in step_list:
                        return i

    def get_last_in_protocol(self):
        step_list = self.steps.all()
        if step_list:
            for i in step_list:
                if not i.next_step:
                    return i
                else:
                    counter = 0
                    for s in i.next_step.all():
                        if s not in step_list:
                            counter += 1
                    if counter == len(i.next_step.all()):
                        return i

    def get_step_in_order(self):
        first_step = self.get_first_in_protocol()
        step_in_protocol = self.steps.all()
        step_list = [first_step]
        if first_step:
            while first_step.next_step:
                steps = first_step.next_step.all()
                count = 0
                for i in steps:
                    if i in step_in_protocol and i not in step_list:
                        first_step = i
                        step_list.append(i)
                        break
                    else:
                        count += 1
                if count == len(steps):
                    break
            return step_list
        return []

    def get_section_in_order(self):
        step_list = self.get_step_in_order()
        section_in_protocol = self.sections.all()
        section_list = []

        for i in step_list:
            if i.step_section in section_in_protocol and i.step_section not in section_list:
                section_list.append(i.step_section)

        return section_list

    def delete(self, using=None, keep_parents=False):
        for session in self.sessions.all():
            session.delete()
        super(ProtocolModel, self).delete(using=using, keep_parents=keep_parents)


class ProtocolStep(models.Model):
    history = HistoricalRecords()
    protocol = models.ForeignKey(ProtocolModel, on_delete=models.CASCADE, related_name="steps", blank=False, null=False)
    step_id = models.BigIntegerField(blank=True, null=True)
    step_description = models.TextField(blank=False, null=False)
    step_section = models.ForeignKey("ProtocolSection", on_delete=models.CASCADE, related_name="steps", blank=True, null=True)
    step_duration = models.IntegerField(blank=True, null=True)
    previous_step = models.ForeignKey("self", on_delete=models.CASCADE, related_name="next_step", blank=True, null=True)
    original = models.BooleanField(default=True)
    branch_from = models.ForeignKey("self", on_delete=models.CASCADE, related_name="branch_steps", blank=True, null=True)
    remote_id = models.BigIntegerField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remote_host = models.ForeignKey("RemoteHost", on_delete=models.CASCADE, related_name="protocol_steps", blank=True, null=True)

    class Meta:
        app_label = "cc"
        ordering = ["id"]

    def __str__(self):
        return self.step_description

    def __repr__(self):
        return self.step_description

    def delete(self, using=None, keep_parents=False):
        #change previous step to next step
        with transaction.atomic():
            if self.next_step:
                next_steps = self.next_step.all()
                previous_step = self.previous_step
                for i in next_steps:
                    if self.previous_step:
                        i.previous_step = previous_step
                        i.save()
                self.next_step.clear()
        super(ProtocolStep, self).delete(using=using, keep_parents=keep_parents)

    def move_up(self):

        if self.previous_step:
            previous_step = self.previous_step
            next_steps = list(self.next_step.all())
            if self.step_section == previous_step.step_section:
                self.next_step.clear()
                if previous_step.previous_step:
                    previous_previous_step = previous_step.previous_step
                    self.previous_step = previous_previous_step
                    self.save()
                    previous_step.previous_step = self
                    previous_step.save()
                    for i in next_steps:
                        i.previous_step = previous_step
                        i.save()
                    print([p.id for p in self.next_step.all()])
                    print([p.id for p in self.next_step.all()[0].next_step.all()])
                else:
                    previous_step.previous_step = self
                    previous_step.save()
                    print(self.previous_step)
                    self.previous_step = None
                    self.save()
                    print(self.previous_step)
                    for i in next_steps:
                        i.previous_step = previous_step
                        i.save()
                        print(i)

                    print([p.id for p in self.next_step.all()])
                    print([p.id for p in self.next_step.all().first().next_step.all()])


    def move_down(self):
        if self.next_step:
            next_steps =list(self.next_step.all())
            if next_steps:
                next_step = next_steps[0]
                if self.step_section == next_step.step_section:
                    self.next_step.remove(next_step)
                    self.save()
                    if next_step.next_step:
                        next_next_step = next_step.next_step.all()
                        for i in next_next_step:
                            i.previous_step = self
                            i.save()
                    next_step.next_step.add(self)
                    self.previous_step = next_step
                    self.save()
                    print(self.previous_step.id)
                    print([p.id for p in self.next_step.all()])

    def process_description_template(self):
        description = self.step_description[:]
        for reagent in self.reagents.all():
            for i in [f"%{reagent.id}.name%", f"%{reagent.id}.quantity%", f"%{reagent.id}.unit%", f"%{reagent.id}.scaled_quantity%"]:
                if i in description:
                    if i == f"%{reagent.id}.name%":
                        description = description.replace(i, reagent.reagent.name)
                    elif i == f"%{reagent.id}.quantity%":
                        description = description.replace(i, str(reagent.quantity))
                    elif i == f"%{reagent.id}.unit%":
                        description = description.replace(i, reagent.reagent.unit)
                    elif i == f"%{reagent.id}.scaled_quantity%":
                        description = description.replace(i, str(reagent.quantity * reagent.scalable_factor))
        return description

    def get_metadata_columns(self, session_unique_id: str):
        session = Session.objects.prefetch_related(
            'protocols__steps__annotations__metadata_columns',
            'protocols__steps__reagents__reagent_actions__reagent__metadata_columns'
        ).get(unique_id=session_unique_id)

        steps_in_order = []
        protocol = self.protocol
        for s in protocol.get_step_in_order():
            steps_in_order.append(s)
            if self.id == s.id:
                break

        metadata_columns = []
        for step in steps_in_order:
            metadata_columns_ids = step.annotations.values_list('metadata_columns', flat=True)
            metadata_columns_ids = [i for i in metadata_columns_ids if i]
            if metadata_columns_ids:
                metadata_columns.extend(MetadataColumn.objects.filter(id__in=[i for i in metadata_columns_ids if i]))
            for reagent in step.reagents.all():
                for action in reagent.reagent_actions.all():
                    metadata_columns.extend(action.reagent.metadata_columns.all())
        print(metadata_columns)
        metadata_columns = list({(m.name, m.type, m.value): {"name": m.name, "type": m.type, "value": m.value} for m in
                                 metadata_columns if m }.values())
        characteristics_columns = [i for i in metadata_columns if i["type"] == "Characteristics"]
        comments_columns = [i for i in metadata_columns if i["type"] == "Comment"]
        factor_value_columns = [i for i in metadata_columns if i["type"] == "Factor value"]
        other_columns = [i for i in metadata_columns if i["type"] not in ["Characteristics", "Comment", "Factor value"]]

        default_columns_characteristics = [dc for dc in default_columns if dc["type"] == "Characteristics"]
        default_columns_other = [dc for dc in default_columns if dc["type"] == "" and dc["name"] != "Source name"]
        default_columns_comment = [dc for dc in default_columns if dc["type"] == "Comment"]
        progress_count = 0

        def update_positions(columns: list, default_cols: list, current_position=0):
            columns_list = [c["name"] for c in columns]
            mandatory = [c for c in default_cols if c in columns_list]
            non_mandatory_columns = [c for c in columns if c["name"] not in default_cols]
            result = []
            for dc in mandatory:
                cols = [c for c in columns if c["name"] == dc]
                for column in cols:
                    column["column_position"] = current_position
                    current_position += 1
                    result.append(column)

            for column in non_mandatory_columns:
                column["column_position"] = current_position
                current_position += 1
                result.append(column)

            return result, current_position

        characteristics_columns, progress_count = update_positions(characteristics_columns,
                                                                   default_columns_characteristics, progress_count)
        other_columns, progress_count = update_positions(other_columns, default_columns_other, progress_count)
        comments_columns, progress_count = update_positions(comments_columns, default_columns_comment, progress_count)
        for i in factor_value_columns:
            i["column_position"] = progress_count
            progress_count += 1
        metadata_columns = characteristics_columns + other_columns + comments_columns + factor_value_columns
        return metadata_columns

    def convert_to_sdrf_file(self, data: list):
        data_position_map = {d["column_position"]: d for d in data}
        positions = data_position_map.keys()
        sorted_positions = sorted(positions)
        row = []
        column_names = []

        for c in sorted_positions:
            column = data_position_map[c]
            column_name = ""
            if column['name'] == "Tissue":
                column_name = f"{column['type']}[organism part]".lower()
            elif column['type'] == "" or not column['type']:
                column_name = f"{column['name']}".lower()
            else:
                column_name = f"{column['type']}[{column['name']}]".lower()
            column_names.append(column_name)
            if column["not_applicable"]:
                row.append("not applicable")
            else:
                if column["value"]:
                    name = column["name"].lower()
                    if name == "organism":
                        species = Species.objects.filter(official_name=column["value"])
                        if species.exists():
                            row.append(f"http://purl.obolibrary.org/obo/NCBITaxon_{species.first().taxon}")
                        else:
                            row.append(column["value"])
                    elif name == "label":
                        vocab = MSUniqueVocabularies.objects.filter(name=column["value"], term_type="sample attribute")
                        if vocab.exists():
                            row.append(f"AC={vocab.first().accession};NT={column['value']}")
                        else:
                            row.append(f"{column['value']}")
                    elif name == "cleavage agent details":
                        vocab = MSUniqueVocabularies.objects.filter(name=column['value'], term_type="cleavage agent")
                        if vocab.exists():
                            row.append(f"AC={vocab.first().accession};NT={column['value']}")
                        else:
                            row.append(f"{column['value']}")
                    elif name == "instrument":
                        vocab = MSUniqueVocabularies.objects.filter(name=column['value'], term_type="instrument")
                        if vocab.exists():
                            row.append(f"AC={vocab.first().accession};NT={column['value']}")
                        else:
                            row.append(f"{column['value']}")
                    elif name == "modification parameters":
                        splitted = column['value'].split(";")
                        unimod = Unimod.objects.filter(name=splitted[0])
                        if unimod.exists():
                            row.append(f"AC={unimod.first().accession};NT={column.value}")
                        else:
                            row.append(f"{column['value']}")
                    elif name == "dissociation method":
                        dissociation = MSUniqueVocabularies.objects.filter(name=column['value'],
                                                                           term_type="dissociation method")
                        if dissociation.exists():
                            row.append(f"AC={dissociation.first().accession};NT={column['value']}")
                        else:
                            row.append(f"{column['value']}")
                    else:
                        row.append(column['value'])
                else:
                    row.append("not available")

        data = [column_names] + [row]
        return data


class ProtocolSection(models.Model):
    history = HistoricalRecords()
    protocol = models.ForeignKey(ProtocolModel, on_delete=models.CASCADE, related_name="sections")
    section_description = models.TextField(blank=True, null=True)
    section_duration = models.IntegerField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remote_id = models.BigIntegerField(blank=True, null=True)
    remote_host = models.ForeignKey("RemoteHost", on_delete=models.CASCADE, related_name="protocol_sections", blank=True, null=True)

    class Meta:
        app_label = "cc"
        ordering = ["id"]

    def __str__(self):
        return self.section_description

    def __repr__(self):
        return self.section_description


    def get_first_in_section(self):
        step_list = self.steps.all()
        if step_list:
            for i in step_list:
                if not i.previous_step:
                    return i
                else:
                    if i.previous_step not in step_list:
                        return i

    def get_last_in_section(self):
        step_list = self.steps.all()
        if step_list:
            for i in step_list:
                if not i.next_step:
                    return i
                else:
                    counter = 0
                    for s in i.next_step.all():
                        if s not in step_list:
                            counter += 1
                    if counter == len(i.next_step.all()):
                        return i

    def get_step_in_order(self):
        first_step = self.get_first_in_section()
        steps_in_section = self.steps.all()
        step_list = [first_step]
        while first_step.next_step:
            steps = first_step.next_step.all()
            count = 0
            for i in steps:
                if i in steps_in_section and i not in step_list:
                    first_step = i
                    step_list.append(i)
                    break
                else:
                    count += 1
            if count == len(steps):
                break
        return step_list

    def insert_step(self, step, previous_step=None, after=True):
        step.step_section = self
        step.save()
        if previous_step:
            if not after:
                if previous_step.previous_step:
                    previous_step = previous_step.previous_step

            next_steps = previous_step.next_step.all()
            previous_step = ProtocolStep.objects.get(id=previous_step.id)
            step.previous_step = previous_step
            step.save()
            for i in next_steps:
                step.next_step.add(i)
                #previous_step.next_step.remove(i)
                i.previous_step = step
                i.save()
                step.save()
            previous_step.next_step.clear()
            previous_step.next_step.add(step)
            previous_step.save()

    def move_section_after(self, previous_section=None):
        if previous_section:
            steps = self.get_step_in_order()
            previous_last_step = previous_section.get_last_in_section()
            if previous_last_step:
                for i in steps:
                    self.insert_step(i, previous_last_step)
                    previous_last_step = i


    def update_steps(self, steps):
        with transaction.atomic():
            for i in steps:
                step = ProtocolStep.objects.get(id=i["id"])
                step.step_duration = i["step_duration"]
                step.step_description = i["step_description"]
                step.save()

    def delete(self, using=None, keep_parents=False):
        if self.steps.all():
            first_step = self.get_first_in_section()
            last_step = self.get_last_in_section()
            previous_step = None
            if first_step.previous_step:
                previous_step = first_step.previous_step
            next_steps = []
            if last_step.next_step:
                next_steps = last_step.next_step.all()
            with transaction.atomic():
                if previous_step:
                    for i in next_steps:
                        previous_step.next_step.add(i)
                        i.previous_step = previous_step
                        i.save()
                else:
                    for i in next_steps:
                        i.previous_step = None
                        i.save()
        super(ProtocolSection, self).delete(using=using, keep_parents=keep_parents)


class Session(models.Model):
    history = HistoricalRecords()
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sessions")
    unique_id = models.UUIDField(blank=False, null=False, unique=True, db_index=True)
    enabled = models.BooleanField(default=False)
    protocols = models.ManyToManyField(ProtocolModel, related_name="sessions", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    name = models.TextField(blank=True, null=True)
    editors = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="editor_sessions", blank=True)
    viewers = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="viewer_sessions", blank=True)
    started_at = models.DateTimeField(blank=True, null=True)
    ended_at = models.DateTimeField(blank=True, null=True)
    remote_id = models.BigIntegerField(blank=True, null=True)
    processing = models.BooleanField(default=False)
    remote_host = models.ForeignKey("RemoteHost", on_delete=models.CASCADE, related_name="sessions", blank=True, null=True)

    class Meta:
        app_label = "cc"
        ordering = ["id"]

    def __str__(self):
        return self.name or f"Session {self.unique_id}"

    @property
    def is_imported(self):
        """Check if this session was imported from another system"""
        return self.name and '[IMPORTED]' in self.name

    @property
    def import_source_info(self):
        """Get information about the import source"""
        try:
            imported_obj = ImportedObject.objects.filter(
                model_name='Session',
                object_id=self.pk
            ).first()
            if imported_obj:
                return {
                    'import_tracker': imported_obj.import_tracker,
                    'original_id': imported_obj.original_id,
                    'imported_at': imported_obj.created_at
                }
        except:
            pass
        return None

    def sync_session_upstream(self, upstream_node_url: str):
        """
        Sync session with upstream node
        :param upstream_node_url:
        :return:
        """


class Instrument(models.Model):
    history = HistoricalRecords()
    instrument_name = models.TextField(blank=False, null=False)
    instrument_description = models.TextField(blank=True, null=True)
    image = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    enabled = models.BooleanField(default=True)
    remote_id = models.BigIntegerField(blank=True, null=True)
    remote_host = models.ForeignKey("RemoteHost", on_delete=models.CASCADE, related_name="instruments", blank=True, null=True)
    max_days_ahead_pre_approval = models.IntegerField(blank=True, null=True, default=0)
    max_days_within_usage_pre_approval = models.IntegerField(blank=True, null=True, default=0)
    support_information = models.ManyToManyField("SupportInformation", blank=True)
    last_warranty_notification_sent = models.DateTimeField(blank=True, null=True)
    last_maintenance_notification_sent = models.DateTimeField(blank=True, null=True)
    days_before_warranty_notification = models.IntegerField(blank=True, null=True, default=30)
    days_before_maintenance_notification = models.IntegerField(blank=True, null=True, default=14)
    accepts_bookings = models.BooleanField(default=True)

    def __str__(self):
        return self.instrument_name
    def __repr__(self):
        return self.instrument_name

    class Meta:
        app_label = "cc"
        ordering = ["id"]

    def create_default_folders(self):
        """
        Create default folders for the instrument
        :return:
        """
        current_folder = self.annotation_folders.all()
        if current_folder.exists():
            return
        manual_folder = AnnotationFolder.objects.create(folder_name="Manuals", instrument=self)
        certificate_folder = AnnotationFolder.objects.create(folder_name="Certificates", instrument=self)
        maintenance = AnnotationFolder.objects.create(folder_name="Maintenance", instrument=self)

    def notify_instrument_managers(self, message: str, subject: str = "Instrument Notification"):
        """
        Notify instrument managers via email
        :param message: Message to send
        :param subject: Subject of the email
        :return:
        """

        manager_permissions = InstrumentPermission.objects.filter(
            instrument=self, can_manage=True
        )

        managers = [perm.user for perm in manager_permissions]

        if not managers:
            return False

        thread = MessageThread.objects.create(
            title=subject or f"Maintenance notification for {self.instrument_name}",
            is_system_thread=True
        )

        for manager in managers:
            thread.participants.add(manager)

        system_message = Message.objects.create(
            thread=thread,
            content=message,
            message_type="system_notification",
            sender=None
        )

        for manager in managers:
            MessageRecipient.objects.create(
                message=system_message,
                user=manager,
                is_read=False
            )

        return True

    @classmethod
    def check_all_instruments(self, days_threshold=30):
        """
        Check all instruments for warranty expiration and upcoming maintenance
        and send notifications for those meeting the threshold criteria

        Args:
            days_threshold: Number of days threshold for notifications

        Returns:
            tuple: (warranty_notification_count, maintenance_notification_count)
        """
        print(days_threshold)
        today = timezone.now().date()

        warranty_count = 0
        maintenance_count = 0

        instruments = self.objects.filter(enabled=True).prefetch_related('support_information')

        for instrument in instruments:
            if instrument.check_warranty_expiration(days_threshold):
                warranty_count += 1

            if instrument.check_upcoming_maintenance(days_threshold):
                maintenance_count += 1

        return warranty_count, maintenance_count

    def check_warranty_expiration(self, days_threshold=30):
        """
        Check if instrument warranty is expiring soon and send notification

        Args:
            days_threshold: Days before expiration to trigger notification

        Returns:
            bool: True if notification was sent, False otherwise
        """

        if not days_threshold:
            days_threshold = self.days_before_warranty_notification or 30


        today = timezone.now().date()

        if self.last_warranty_notification_sent and timezone.now() - self.last_warranty_notification_sent < timedelta(
                days=7):
            return False

        for support_info in self.support_information.all():
            if not support_info.warranty_end_date:
                continue

            days_remaining = (support_info.warranty_end_date - today).days

            if 0 < days_remaining <= days_threshold:
                subject = f"Warranty Expiration Alert - {self.instrument_name}"
                message = (
                    f"⚠️ **Warranty Expiration Alert**<br>"
                    f"The warranty for {self.instrument_name} will expire in {days_remaining} "
                    f"{'day' if days_remaining == 1 else 'days'} on {support_info.warranty_end_date.strftime('%Y-%m-%d')}.<br>"
                )

                if support_info.vendor_name:
                    message += f"**Vendor:** {support_info.vendor_name}<br>"

                    vendor_contacts = support_info.vendor_contacts.all()
                    if vendor_contacts.exists():
                        message += "**Vendor Contacts:**<br>"
                        for contact in vendor_contacts:
                            message += f"- {contact.contact_name}<br>"
                            for detail in contact.contact_details.all():
                                message += f"  {detail.contact_type}: {detail.contact_value}<br>"

                if self.notify_instrument_managers(message, subject):
                    self.last_warranty_notification_sent = timezone.now()
                    self.save(update_fields=['last_warranty_notification_sent'])
                    return True

        return False

    def check_upcoming_maintenance(self, days_threshold=14):
        """
        Check if instrument is due for maintenance and send notification

        Args:
            days_threshold: Days before maintenance to trigger notification

        Returns:
            bool: True if notification was sent, False otherwise
        """
        if not days_threshold:
            days_threshold = self.days_before_maintenance_notification or 14
        print(days_threshold)
        today = timezone.now().date()

        if self.last_maintenance_notification_sent and timezone.now() - self.last_maintenance_notification_sent < timedelta(
                days=7):
            return False

        for support_info in self.support_information.all():
            if not support_info.maintenance_frequency_days:
                continue

            last_maintenance = self.maintenance_logs.filter(
                status='completed'
            ).order_by('-maintenance_date').first()

            if last_maintenance:
                next_maintenance_date = (
                        last_maintenance.maintenance_date.date() +
                        timedelta(days=support_info.maintenance_frequency_days)
                )

                days_remaining = (next_maintenance_date - today).days

                if 0 < days_remaining <= days_threshold:
                    subject = f"Scheduled Maintenance Reminder - {self.instrument_name}"
                    message = (
                        f"🔧 **Scheduled Maintenance Reminder**<br>"
                        f"The {self.instrument_name} is due for maintenance in {days_remaining} <br>"
                        f"{'day' if days_remaining == 1 else 'days'} on {next_maintenance_date.strftime('%Y-%m-%d')}.<br>"
                        f"Last maintenance was performed on {last_maintenance.maintenance_date.strftime('%Y-%m-%d')}.<br>"
                    )

                    message += f"\nMaintenance frequency: Every {support_info.maintenance_frequency_days} days<br>"

                    if self.notify_instrument_managers(message, subject):
                        self.last_maintenance_notification_sent = timezone.now()
                        self.save(update_fields=['last_maintenance_notification_sent'])
                        return True
            else:
                if support_info.maintenance_frequency_days <= days_threshold:
                    subject = f"Initial Maintenance Required - {self.instrument_name}"
                    message = (
                        f"🔧 **Initial Maintenance Required**<br>"
                        f"The {self.instrument_name} requires initial maintenance as no previous logs exist.<br>"
                        f"Please schedule maintenance as soon as possible.<br>"
                    )

                    if self.notify_instrument_managers(message, subject):
                        self.last_maintenance_notification_sent = timezone.now()
                        self.save(update_fields=['last_maintenance_notification_sent'])
                        return True

        return False


class InstrumentUsage(models.Model):
    history = HistoricalRecords()
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="instrument_usage")
    annotation = models.ForeignKey("Annotation", on_delete=models.CASCADE, related_name="instrument_usage", blank=True, null=True)
    time_started = models.DateTimeField(blank=True, null=True)
    time_ended = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remote_id = models.BigIntegerField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="instrument_usage", blank=True, null=True)
    remote_host = models.ForeignKey("RemoteHost", on_delete=models.CASCADE, related_name="instrument_usages", blank=True, null=True)
    approved = models.BooleanField(default=False)
    maintenance = models.BooleanField(default=False)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="approved_by_instrument_usage", blank=True, null=True)

    class Meta:
        app_label = "cc"
        ordering = ["id"]



class InstrumentPermission(models.Model):
    history = HistoricalRecords()
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="instrument_permissions")
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="instrument_permissions")
    can_view = models.BooleanField(default=False)
    can_book = models.BooleanField(default=False)
    can_manage = models.BooleanField(default=False)


class Annotation(models.Model):
    history = HistoricalRecords()
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="annotations", blank=True, null=True)
    step = models.ForeignKey(ProtocolStep, on_delete=models.CASCADE, related_name="annotations", blank=True, null=True)
    stored_reagent = models.ForeignKey("StoredReagent", on_delete=models.CASCADE, related_name="annotations", blank=True, null=True)
    annotation = models.TextField(blank=False, null=False)
    file = models.FileField(blank=True, null=True, upload_to="annotations/")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    transcribed = models.BooleanField(default=False)
    transcription = models.TextField(blank=True, null=True)
    language = models.TextField(blank=True, null=True)
    translation = models.TextField(blank=True, null=True)
    scratched = models.BooleanField(default=False)
    annotation_type_choices = [
        ("text", "Text"),
        ("file", "File"),
        ("image", "Image"),
        ("video", "Video"),
        ("audio", "Audio"),
        ("sketch", "Sketch"),
        ("other", "Other"),
        ("checklist", "Checklist"),
        ("counter", "Counter"),
        ("table", "Table"),
        ("alignment", "Alignment"),
        ("calculator", "Calculator"),
        ("mcalculator", "Molarity Calculator"),
        ("randomization", "Randomization"),
        ("instrument", "Instrument"),
        ("metadata", "Metadata"),
    ]
    annotation_type = models.CharField(max_length=20, choices=annotation_type_choices, default="text")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="annotations", blank=True, null=True)
    remote_id = models.BigIntegerField(blank=True, null=True)
    folder = models.ForeignKey("AnnotationFolder", on_delete=models.CASCADE, related_name="annotations", blank=True, null=True)
    annotation_name = models.TextField(blank=True, null=True)
    summary = models.TextField(blank=True, null=True)
    remote_host = models.ForeignKey("RemoteHost", on_delete=models.CASCADE, related_name="annotations", blank=True, null=True)
    fixed = models.BooleanField(default=False)

    class Meta:
        app_label = "cc"
        ordering = ["id"]

    def __str__(self):
        return self.annotation

    @property
    def is_imported(self):
        """Check if this annotation was imported from another system"""
        return (self.annotation_name and '[IMPORTED]' in self.annotation_name) or \
               (self.annotation and '[IMPORTED' in self.annotation)

    @property
    def was_converted_from_instrument(self):
        """Check if this annotation was converted from an instrument booking"""
        return self.annotation_type == 'text' and \
               self.annotation and '[IMPORTED INSTRUMENT BOOKING' in self.annotation

    @property
    def import_source_info(self):
        """Get information about the import source"""
        try:
            imported_obj = ImportedObject.objects.filter(
                model_name='Annotation',
                object_id=self.pk
            ).first()
            if imported_obj:
                return {
                    'import_tracker': imported_obj.import_tracker,
                    'original_id': imported_obj.original_id,
                    'imported_at': imported_obj.created_at
                }
        except:
            pass
        return None

    def __repr__(self):
        return self.annotation

    def delete(self, using=None, keep_parents=False):
        if self.file:
            self.file.delete()
        super(Annotation, self).delete(using=using, keep_parents=keep_parents)

    def check_for_right(self, user, right: str) -> bool:
        # Check shared document permissions first

        if self.folder and self.folder.is_shared_document_folder:
            permission_map = {
                'view': 'can_view',
                'edit': 'can_edit', 
                'delete': 'can_delete'
            }
            required_permission = permission_map.get(right)
            if required_permission:
                return DocumentPermission.user_can_access_annotation_with_folder_inheritance(self, user, required_permission)
        
        if self.session:
            if self.session.enabled:
                if not self.scratched:
                    if right == "view":
                        return True


        if user.is_authenticated:
            if self.session:
                if right == "view":
                    if user in self.session.viewers.all() or user in self.session.editors.all() or user == self.session.user or user == self.user:
                        if self.scratched:
                            if user not in self.session.editors.all() and user != self.user and user != self.session.user:
                                return False
                        return True
                elif right == "delete" or right == "edit":
                    if user in self.session.editors.all() or user == self.session.user:
                        return True
            if self.folder:
                if self.folder.instrument:
                    i_permission = InstrumentPermission.objects.filter(instrument=self.folder.instrument, user=user)
                    if i_permission.exists():
                        i_permission = i_permission.first()
                        if right == "view":
                            if i_permission.can_book or i_permission.can_manage or i_permission.can_view:
                                    return True
                        if right == "delete" or right == "edit":
                            if i_permission.can_manage:
                                return True
            else:
                if not self.instrument_jobs.exists():
                    permission_map = {
                        'view': 'can_view',
                        'edit': 'can_edit',
                        'delete': 'can_delete'
                    }
                    required_permission = permission_map.get(right)
                    if required_permission:
                        return DocumentPermission.user_can_access_annotation_with_folder_inheritance(self, user,
                                                                                                     required_permission)
                instrument_jobs = self.instrument_jobs.all()
                for instrument_job in instrument_jobs:
                    if right == "view":
                        if user == instrument_job.user:
                            return True
                        else:
                            lab_group = instrument_job.service_lab_group
                            staff =  instrument_job.staff.all()
                            if staff.count() > 0:
                                if user in staff:
                                    return True
                            else:
                                if user in lab_group.users.all():
                                    return True
                    if right == "delete" or right == "edit":
                        if user == instrument_job.user:
                            return True
                        else:
                            lab_group = instrument_job.service_lab_group
                            staff =  instrument_job.staff.all()
                            if staff.count() > 0:
                                if user in staff:
                                    return True
                            else:
                                if user in lab_group.users.all():
                                    return True
        return False

class AnnotationFolder(models.Model):
    history = HistoricalRecords()
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="annotation_folders", blank=True, null=True)
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="annotation_folders", blank=True, null=True)
    stored_reagent = models.ForeignKey("StoredReagent", on_delete=models.CASCADE, related_name="annotation_folders", blank=True, null=True)
    folder_name = models.TextField(blank=False, null=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    parent_folder = models.ForeignKey("self", on_delete=models.CASCADE, related_name="child_folders", blank=True, null=True)
    is_shared_document_folder = models.BooleanField(default=False, help_text="Indicates if this folder is specifically for shared documents (file annotations)")
    owner = models.ForeignKey("auth.User", on_delete=models.CASCADE, related_name="owned_annotation_folders", blank=True, null=True, help_text="User who owns this folder")
    remote_id = models.BigIntegerField(blank=True, null=True)
    remote_host = models.ForeignKey("RemoteHost", on_delete=models.CASCADE, related_name="annotation_folders", blank=True, null=True)

    class Meta:
        app_label = "cc"
        ordering = ["id"]

    def __str__(self):
        return self.folder_name

    def __repr__(self):
        return self.folder_name

    def delete(self, using=None, keep_parents=False):
        super(AnnotationFolder, self).delete(using=using, keep_parents=keep_parents)

class StepVariation(models.Model):
    history = HistoricalRecords()
    step = models.ForeignKey(ProtocolStep, on_delete=models.CASCADE, related_name="variations")
    variation_description = models.TextField(blank=False, null=False)
    variation_duration = models.IntegerField(blank=False, null=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remote_id = models.BigIntegerField(blank=True, null=True)
    remote_host = models.ForeignKey("RemoteHost", on_delete=models.CASCADE, related_name="step_variations", blank=True, null=True)

    class Meta:
        app_label = "cc"
        ordering = ["id"]

    def __str__(self):
        return self.variation_description

    def __repr__(self):
        return self.variation_description

class TimeKeeper(models.Model):
    history = HistoricalRecords()
    start_time = models.DateTimeField(auto_now=True)
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="time_keeper", blank=True, null=True)
    step = models.ForeignKey(ProtocolStep, on_delete=models.CASCADE, related_name="time_keeper", blank=True, null=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="time_keeper")
    started = models.BooleanField(default=False)
    current_duration = models.IntegerField(blank=True, null=True)
    remote_id = models.BigIntegerField(blank=True, null=True)
    remote_host = models.ForeignKey("RemoteHost", on_delete=models.CASCADE, related_name="time_keeper", blank=True, null=True)
    

    class Meta:
        app_label = "cc"
        ordering = ["id"]

    def __str__(self):
        return f"{self.start_time} - {self.session} - {self.step}"

    def __repr__(self):
        return f"{self.start_time} - {self.session} - {self.step}"


class WebRTCSession(models.Model):
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="webrtc_session")
    session_unique_id = models.TextField(blank=True, null=True)
    session_token = models.TextField(blank=True, null=True)
    session_key = models.TextField(blank=True, null=True)
    session_secret = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    users = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="webrtc_sessions", blank=True)
    user_channels = models.ManyToManyField("WebRTCUserChannel", related_name="webrtc_sessions", blank=True)

    class Meta:
        app_label = "cc"
        ordering = ["id"]

    def __str__(self):
        return self.session_unique_id

    def __repr__(self):
        return self.session_unique_id

    def delete(self, using=None, keep_parents=False):
        super(WebRTCSession, self).delete(using=using, keep_parents=keep_parents)

class WebRTCUserChannel(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="webrtc_user_channels")
    channel_id = models.TextField(blank=False, null=False)
    channel_type_choices = [
        ("viewer", "Viewer"),
        ("host", "Host"),
    ]
    channel_type = models.CharField(max_length=10, choices=channel_type_choices, default="viewer")

    class Meta:
        app_label = "cc"
        ordering = ["id"]

class WebRTCUserOffer(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="webrtc_user_offers")
    sdp = models.JSONField(blank=False, null=False)
    session = models.ForeignKey(WebRTCSession, on_delete=models.CASCADE, related_name="webrtc_user_offers")
    from_id = models.TextField(blank=False, null=False)

    id_type_choices = [
        ("viewer", "Viewer"),
        ("host", "Host"),
    ]
    id_type = models.CharField(max_length=10, choices=id_type_choices, default="viewer")

    class Meta:
        app_label = "cc"
        ordering = ["id"]


class Reagent(models.Model):
    history = HistoricalRecords()
    name = models.CharField(max_length=255)
    unit = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class ProtocolReagent(models.Model):
    history = HistoricalRecords()
    protocol = models.ForeignKey(ProtocolModel, on_delete=models.CASCADE, related_name="reagents")
    reagent = models.ForeignKey(Reagent, on_delete=models.CASCADE)
    quantity = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remote_id = models.BigIntegerField(blank=True, null=True)


class StepReagent(models.Model):
    history = HistoricalRecords()
    step = models.ForeignKey(ProtocolStep, on_delete=models.CASCADE, related_name="reagents")
    reagent = models.ForeignKey(Reagent, on_delete=models.CASCADE)
    quantity = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    scalable = models.BooleanField(default=False)
    scalable_factor = models.FloatField(default=1.0)
    remote_id = models.BigIntegerField(blank=True, null=True)

class Tag(models.Model):
    history = HistoricalRecords()
    tag = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remote_id = models.BigIntegerField(blank=True, null=True)

    class Meta:
        app_label = "cc"
        ordering = ["id"]

    def __str__(self):
        return self.tag

    def __repr__(self):
        return self.tag

    def delete(self, using=None, keep_parents=False):
        super(Tag, self).delete(using=using, keep_parents=keep_parents)

class ProtocolTag(models.Model):
    history = HistoricalRecords()
    protocol = models.ForeignKey(ProtocolModel, on_delete=models.CASCADE, related_name="tags")
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remote_id = models.BigIntegerField(blank=True, null=True)

    class Meta:
        app_label = "cc"
        ordering = ["id"]

    def __str__(self):
        return self.tag

    def __repr__(self):
        return self.tag

    def delete(self, using=None, keep_parents=False):
        super(ProtocolTag, self).delete(using=using, keep_parents=keep_parents)


class StepTag(models.Model):
    history = HistoricalRecords()
    step = models.ForeignKey(ProtocolStep, on_delete=models.CASCADE, related_name="tags")
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remote_id = models.BigIntegerField(blank=True, null=True)

    class Meta:
        app_label = "cc"
        ordering = ["id"]

    def __str__(self):
        return self.tag

    def __repr__(self):
        return self.tag

    def delete(self, using=None, keep_parents=False):
        super(StepTag, self).delete(using=using, keep_parents=keep_parents)


class RemoteHost(models.Model):
    history = HistoricalRecords()
    host_name = models.CharField(max_length=255)
    host_port = models.IntegerField()
    host_protocol = models.CharField(max_length=255)
    host_description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    host_token = models.TextField(blank=True, null=True)
    host_type_choices = [
        ("cupcake", "Cupcake"),
    ]

    class Meta:
        app_label = "cc"
        ordering = ["id"]

    def encrypt_token(self, token: str):
        # encrypt token using django secret key
        self.host_token = signing.dumps(token)

    def decrypt_token(self):
        try:
            return signing.loads(self.host_token)
        except signing.BadSignature:
            return None


class StorageObject(models.Model):
    history = HistoricalRecords()
    object_type_choices = [
        ("shelf", "Shelf"),
        ("box", "Box"),
        ("fridge", "Fridge"),
        ("freezer", "Freezer"),
        ("room", "Room"),
        ("building", "Building"),
        ("floor", "Floor"),
        ("other", "Other"),
    ]

    object_type = models.CharField(max_length=20, choices=object_type_choices, default="shelf")
    object_name = models.TextField(blank=False, null=False)
    object_description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    stored_at = models.ForeignKey("StorageObject", on_delete=models.CASCADE, related_name="storage_objects", blank=True, null=True)
    remote_id = models.BigIntegerField(blank=True, null=True)
    remote_host = models.ForeignKey("RemoteHost", on_delete=models.CASCADE, related_name="storage_objects", blank=True, null=True)
    can_delete = models.BooleanField(default=False)
    png_base64 = models.TextField(blank=True, null=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="storage_objects", blank=True, null=True)
    access_lab_groups = models.ManyToManyField("LabGroup", related_name="storage_objects", blank=True)


    class Meta:
        app_label = "cc"
        ordering = ["id"]

    def get_all_children(self):
        children = []
        for i in self.storage_objects.all():
            children.append(i)
            children += i.get_all_children()
        return children

    def get_path_to_root(self):
        path = [{"id": self.id, "name": self.object_name[:]}]
        storage_object = self
        while storage_object.stored_at:
            storage_object = storage_object.stored_at
            path.append({"id": storage_object.id, "name": storage_object.object_name[:]})
        path.reverse()
        return path



class StoredReagent(models.Model):
    history = HistoricalRecords()
    reagent = models.ForeignKey(Reagent, on_delete=models.CASCADE, related_name="stored_reagents")
    storage_object = models.ForeignKey(StorageObject, on_delete=models.CASCADE, related_name="stored_reagents")
    quantity = models.FloatField()
    notes = models.TextField(blank=True, null=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="stored_reagents", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remote_id = models.BigIntegerField(blank=True, null=True)
    remote_host = models.ForeignKey("RemoteHost", on_delete=models.CASCADE, related_name="stored_reagents", blank=True, null=True)
    png_base64 = models.TextField(blank=True, null=True)
    barcode = models.TextField(blank=True, null=True)
    shareable = models.BooleanField(default=True)
    access_users = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="shared_reagents", blank=True)
    access_lab_groups = models.ManyToManyField("LabGroup", related_name="shared_reagents", blank=True)
    access_all = models.BooleanField(default=False)
    expiration_date = models.DateField(blank=True, null=True)
    created_by_project = models.ForeignKey("Project", on_delete=models.CASCADE, related_name="created_reagents", blank=True, null=True)
    created_by_protocol = models.ForeignKey(ProtocolModel, on_delete=models.CASCADE, related_name="created_reagents", blank=True, null=True)
    created_by_step = models.ForeignKey(ProtocolStep, on_delete=models.CASCADE, related_name="created_reagents", blank=True, null=True)
    created_by_session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="created_reagents", blank=True, null=True)
    low_stock_threshold = models.FloatField(blank=True, null=True,
                                            help_text="Threshold quantity for low stock notifications")
    notify_on_low_stock = models.BooleanField(default=False)
    last_notification_sent = models.DateTimeField(blank=True, null=True)
    notify_days_before_expiry = models.IntegerField(blank=True, null=True, default=14,
                                                    help_text="Days before expiration to send notification")
    notify_on_expiry = models.BooleanField(default=False)
    last_expiry_notification_sent = models.DateTimeField(blank=True, null=True)

    class Meta:
        app_label = "cc"
        ordering = ["id"]

    def get_current_quantity(self):
        actions = self.reagent_actions.all()
        quantity = self.quantity
        for i in actions:
            if i.action_type == "add":
                quantity += i.quantity
            else:
                quantity -= i.quantity
        return quantity

    def create_default_folders(self):
        """
        Create default folders for the stored reagent
        :return:
        """
        current_folder = self.annotation_folders.all()
        if current_folder.exists():
            return
        manual_folder = AnnotationFolder.objects.create(folder_name="Manuals", stored_reagent=self)
        certificate_folder = AnnotationFolder.objects.create(folder_name="Certificates", stored_reagent=self)
        msds_folder = AnnotationFolder.objects.create(folder_name="MSDS", stored_reagent=self)

    def check_low_stock(self):
        """Check if current quantity is below threshold and send notification if needed"""
        current_quantity = self.get_current_quantity()
        if self.low_stock_threshold and current_quantity <= self.low_stock_threshold:
            self.send_low_stock_notification(current_quantity)
            return True
        return False

    def send_low_stock_notification(self, current_quantity):
        """Send a low stock notification to the reagent owner and subscribers"""
        # Create the notification thread
        thread = MessageThread.objects.create(
            title=f"Low Stock Alert: {self.reagent.name}",
            is_system_thread=True,
            creator=self.user
        )

        # Format the message content
        content = f"""
        <h3 style="color: #d9534f;">⚠️ Low Stock Alert</h3>
        <div style="padding: 10px; border-left: 3px solid #d9534f; margin-bottom: 15px;">
            <p><strong>Reagent:</strong> <a href="{self.get_item_link()}">{self.reagent.name}</a></p>
            <p><strong>Current quantity:</strong> {current_quantity} {self.reagent.unit}</p>
            <p><strong>Threshold:</strong> {self.low_stock_threshold} {self.reagent.unit}</p>
            <p><strong>Storage location:</strong> {self.storage_object.object_name}</p>
            <p><strong>Path to storage:</strong> {"/".join([i["name"] for i in self.storage_object.get_path_to_root()])}</p>
            <p><strong>Expiration date:</strong> {self.expiration_date.strftime('%Y-%m-%d') if self.expiration_date else 'Not specified'}</p>
        </div>
        <p>Please restock this reagent soon to ensure continued availability for experiments.</p>
        """

        # Create the alert message
        message = Message.objects.create(
            thread=thread,
            sender=None,  # System message
            content=content,
            message_type="alert",
            priority="high",
            stored_reagent=self
        )

        for subscription in self.subscriptions.filter(notify_on_low_stock=True):
            if subscription.notify_on_low_stock:
                thread.participants.add(subscription.user)
                MessageRecipient.objects.create(
                    message=message,
                    user=subscription.user,
                    is_read=False
                )

        self.last_notification_sent = timezone.now()
        self.save(update_fields=['last_notification_sent'])

    def check_expiration(self):
        """Check if reagent is approaching expiration date and send notification if needed"""
        if self.expiration_date:
            days_until_expiry = (self.expiration_date - timezone.now().date()).days
            if days_until_expiry <= self.notify_days_before_expiry:
                self.send_expiry_notification(days_until_expiry)
                return True
        return False

    def send_expiry_notification(self, days_until_expiry):
        """Send an expiration notification to the reagent owner and subscribers"""
        # Create the notification thread
        thread = MessageThread.objects.create(
            title=f"Expiration Alert: {self.reagent.name}",
            is_system_thread=True,
            creator=self.user
        )

        # Format the message content
        content = f"""
        <h3 style="color: #d9534f;">⚠️ Expiration Alert</h3>
        <div style="padding: 10px; border-left: 3px solid #d9534f; margin-bottom: 15px;">
            <p><strong>Reagent:</strong> <a href="{self.get_item_link()}">{self.reagent.name}</a></p>
            <p><strong>Expiration date:</strong> {self.expiration_date.strftime('%Y-%m-%d')}</p>
            <p><strong>Days until expiry:</strong> {days_until_expiry}</p>
            <p><strong>Current quantity:</strong> {self.get_current_quantity()} {self.reagent.unit}</p>
            <p><strong>Storage location:</strong> {self.storage_object.object_name}</p>
            <p><strong>Path to storage:</strong> {"/".join([i["name"] for i in self.storage_object.get_path_to_root()])}</p>
        </div>
        <p>This reagent will expire soon. Please check if it needs to be replaced or discarded.</p>
        """

        # Create the alert message
        message = Message.objects.create(
            thread=thread,
            sender=None,  # System message
            content=content,
            message_type="alert",
            priority="high",
            stored_reagent=self
        )

        # Notify subscribers who opted for expiry notifications
        for subscription in self.subscriptions.filter(notify_on_expiry=True):
            if subscription.notify_on_expiry:
                thread.participants.add(subscription.user)
                MessageRecipient.objects.create(
                    message=message,
                    user=subscription.user,
                    is_read=False
                )

        # Update the last notification timestamp
        self.last_expiry_notification_sent = timezone.now()
        self.save(update_fields=['last_expiry_notification_sent'])

    def get_item_link(self):
        """
        Get the link to the item in the inventory system
        :return:
        """

        return f"/#/reagent-store/{self.storage_object.id}/{self.id}"

    def subscribe_user(self, user, notify_low_stock=False, notify_expiry=False):
        """Subscribe a user to notifications for this reagent"""
        subscription, created = ReagentSubscription.objects.get_or_create(
            user=user,
            stored_reagent=self,
            defaults={
                'notify_on_low_stock': notify_low_stock,
                'notify_on_expiry': notify_expiry
            }
        )

        if not created:
            if notify_low_stock:
                subscription.notify_on_low_stock = True
            if notify_expiry:
                subscription.notify_on_expiry = True
            subscription.save()

        return subscription

    def unsubscribe_user(self, user, notify_low_stock=False, notify_expiry=False):
        try:
            subscription = self.subscriptions.get(user=user)

            if notify_low_stock and notify_expiry:
                subscription.delete()
                return True

            if notify_low_stock:
                subscription.notify_on_low_stock = False
            if notify_expiry:
                subscription.notify_on_expiry = False

            if not subscription.notify_on_low_stock and not subscription.notify_on_expiry:
                subscription.delete()
            else:
                subscription.save()

            return True
        except ReagentSubscription.DoesNotExist:
            return False

    def get_subscribers(self):
        return [subscription.user for subscription in self.subscriptions.all()]


class ReagentSubscription(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="reagent_subscriptions")
    stored_reagent = models.ForeignKey(StoredReagent, on_delete=models.CASCADE,
                                       related_name="subscriptions")
    notify_on_low_stock = models.BooleanField(default=True)
    notify_on_expiry = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "cc"
        unique_together = ['user', 'stored_reagent']

    def __str__(self):
        return f"{self.user.username} - {self.stored_reagent.reagent.name}"

class ReagentAction(models.Model):
    history = HistoricalRecords()
    action_type_choices = [
        ("add", "Add"),
        ("reserve", "Reserve"),
    ]
    action_type = models.CharField(max_length=20, choices=action_type_choices, default="add")
    reagent = models.ForeignKey(StoredReagent, on_delete=models.CASCADE, related_name="reagent_actions")
    quantity = models.FloatField(default=0)
    notes = models.TextField(blank=True, null=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name="reagent_actions", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    step_reagent = models.ForeignKey(StepReagent, on_delete=models.SET_NULL, related_name="reagent_actions", blank=True, null=True)
    session = models.ForeignKey(Session, on_delete=models.SET_NULL, related_name="reagent_actions", blank=True, null=True)

    class Meta:
        app_label = "cc"
        ordering = ["id"]

class LabGroup(models.Model):
    history = HistoricalRecords()
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remote_id = models.BigIntegerField(blank=True, null=True)
    remote_host = models.ForeignKey("RemoteHost", on_delete=models.CASCADE, related_name="lab_groups", blank=True, null=True)
    users = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="lab_groups", blank=True)
    managers = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="managed_lab_groups", blank=True)
    default_storage = models.ForeignKey(StorageObject, on_delete=models.SET_NULL, related_name="lab_groups", blank=True, null=True)
    is_professional = models.BooleanField(default=False)
    service_storage = models.ForeignKey(StorageObject, on_delete=models.SET_NULL, related_name="service_lab_groups", blank=True, null=True)

    class Meta:
        app_label = "cc"
        ordering = ["id"]

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name

    def delete(self, using=None, keep_parents=False):
        super(LabGroup, self).delete(using=using, keep_parents=keep_parents)


class MetadataColumn(models.Model):
    name = models.CharField(max_length=255)
    type = models.CharField(max_length=255)
    column_position = models.IntegerField(blank=True, null=True, default=0)
    value = models.TextField(blank=True, null=True)
    not_applicable = models.BooleanField(default=False)
    stored_reagent = models.ForeignKey(StoredReagent, on_delete=models.CASCADE, related_name="metadata_columns", blank=True, null=True)
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="metadata_columns", blank=True, null=True)
    annotation = models.ForeignKey(Annotation, on_delete=models.CASCADE, related_name="metadata_columns", blank=True, null=True)
    protocol = models.ForeignKey(ProtocolModel, on_delete=models.CASCADE, related_name="metadata_columns", blank=True, null=True)
    mandatory = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    modifiers = models.TextField(blank=True, null=True)
    hidden = models.BooleanField(default=False)
    auto_generated = models.BooleanField(default=False)
    readonly = models.BooleanField(default=False)

    class Meta:
        ordering = ['id']
        app_label = 'cc'

    def __str__(self):
        return self.name



class Tissue(models.Model):
    """Storing unique vocabulary of tissues from uniprot"""
    identifier = models.CharField(max_length=255, primary_key=True)
    accession = models.CharField(max_length=255)
    synonyms = models.TextField(blank=True, null=True)
    cross_references = models.TextField(blank=True, null=True)

    class Meta:
        app_label = 'cc'
        ordering = ['identifier']

    def __str__(self):
        return self.identifier

class HumanDisease(models.Model):
    """Storing unique vocabulary of human diseases from uniprot"""
    identifier = models.CharField(max_length=255, primary_key=True)
    acronym = models.CharField(max_length=255, blank=True, null=True)
    accession = models.CharField(max_length=255)
    definition = models.TextField(blank=True, null=True)
    synonyms = models.TextField(blank=True, null=True)
    cross_references = models.TextField(blank=True, null=True)
    keywords = models.TextField(blank=True, null=True)

    class Meta:
        app_label = 'cc'
        ordering = ['identifier']

    def __str__(self):
        return self.identifier

class MSUniqueVocabularies(models.Model):
    """Storing unique vocabulary of mass spectrometry from HUPO-PSI"""
    accession = models.CharField(max_length=255, primary_key=True)
    name = models.CharField(max_length=255)
    definition = models.TextField(blank=True, null=True)
    term_type = models.TextField(blank=True, null=True)

    class Meta:
        app_label = 'cc'
        ordering = ['accession']

    def __str__(self):
        return self.accession

class Species(models.Model):
    """ A model to store UniProt species information"""
    code = models.CharField(max_length=255)
    taxon = models.IntegerField()
    official_name = models.CharField(max_length=255)
    common_name = models.CharField(max_length=255, blank=True, null=True)
    synonym = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        app_label = 'cc'
        ordering = ['official_name']

class SubcellularLocation(models.Model):
    """ A model to store UniProt subcellular location information"""
    location_identifier = models.TextField(blank=True, null=True)
    topology_identifier = models.TextField(blank=True, null=True)
    orientation_identifier = models.TextField(blank=True, null=True)
    accession = models.CharField(max_length=255, primary_key=True)
    definition = models.TextField(blank=True, null=True)
    synonyms = models.TextField(blank=True, null=True)
    content = models.TextField(blank=True, null=True)
    is_a = models.TextField(blank=True, null=True)
    part_of = models.TextField(blank=True, null=True)
    keyword = models.TextField(blank=True, null=True)
    gene_ontology = models.TextField(blank=True, null=True)
    annotation = models.TextField(blank=True, null=True)
    references = models.TextField(blank=True, null=True)
    links = models.TextField(blank=True, null=True)

    class Meta:
        app_label = 'cc'
        ordering = ['accession']

class Unimod(models.Model):
    """Storing unique vocabulary of mass spectrometry from Unimod"""
    accession = models.CharField(max_length=255, primary_key=True)
    name = models.CharField(max_length=255)
    definition = models.TextField(blank=True, null=True)
    additional_data = models.JSONField(blank=True, null=True)

    class Meta:
        app_label = 'cc'
        ordering = ['accession']

    def __str__(self):
        return self.accession

class InstrumentJob(models.Model):
    history = HistoricalRecords()
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name='instrument_jobs', blank=True, null=True)
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, related_name='instrument_jobs', blank=True, null=True)
    instrument = models.ForeignKey(Instrument, on_delete=models.SET_NULL, related_name='instrument_jobs', blank=True, null=True)
    protocol = models.ForeignKey(ProtocolModel, on_delete=models.SET_NULL, related_name='instrument_jobs', blank=True, null=True)
    session = models.ForeignKey(Session, on_delete=models.SET_NULL, related_name='instrument_jobs', blank=True, null=True)
    job_type_choices = [
        ('maintenance', 'Maintenance'),
        ('analysis', 'Analysis'),
        ('other', 'Other'),
    ]
    job_type = models.CharField(max_length=20, choices=job_type_choices, default='analysis')
    user_annotations = models.ManyToManyField(Annotation, related_name='instrument_jobs', blank=True)
    staff_annotations = models.ManyToManyField(Annotation, related_name='assigned_instrument_jobs', blank=True)
    assigned = models.BooleanField(default=False)
    staff = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='assigned_instrument_jobs', blank=True)
    service_lab_group = models.ForeignKey(LabGroup, on_delete=models.SET_NULL, related_name='instrument_jobs', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    instrument_usage = models.ForeignKey(InstrumentUsage, on_delete=models.SET_NULL, related_name='instrument_jobs', blank=True, null=True)
    status_choices = [
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('in_progress', 'In Progress'),
        ('cancelled', 'Cancelled'),
    ]
    status = models.CharField(max_length=20, choices=status_choices, default='draft')
    job_name = models.TextField(blank=True, null=True)
    user_metadata = models.ManyToManyField(MetadataColumn, related_name='instrument_jobs', blank=True)
    staff_metadata = models.ManyToManyField(MetadataColumn, related_name='assigned_instrument_jobs', blank=True)
    sample_number = models.IntegerField(blank=True, null=True)
    sample_type_choices = [
        ('wcl', 'Whole Cell Lysate'),
        ('ip', 'Immunoprecipitate'),
        ('other', 'Other'),
    ]
    sample_type = models.CharField(max_length=20, choices=sample_type_choices, default='other')
    funder = models.TextField(blank=True, null=True)
    cost_center = models.TextField(blank=True, null=True)
    injection_volume = models.FloatField(blank=True, null=True)
    injection_unit = models.TextField(blank=True, null=True, default='uL')
    search_engine = models.TextField(blank=True, null=True)
    search_engine_version = models.TextField(blank=True, null=True)
    search_details = models.TextField(blank=True, null=True)
    location = models.TextField(blank=True, null=True)
    stored_reagent = models.ForeignKey(StoredReagent, on_delete=models.SET_NULL, related_name='instrument_jobs', blank=True, null=True)
    selected_template = models.ForeignKey("MetadataTableTemplate", on_delete=models.SET_NULL, related_name='instrument_jobs', blank=True, null=True)
    submitted_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    method = models.TextField(blank=True, null=True)

    class Meta:
        app_label = 'cc'
        ordering = ['-id']

class Preset(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name='presets', blank=True, null=True)

    class Meta:
        app_label = 'cc'
        ordering = ['id']

class FavouriteMetadataOption(models.Model):
    history = HistoricalRecords()
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name='favourite_metadata_options', blank=True, null=True)
    name = models.CharField(max_length=255)
    type = models.CharField(max_length=255)
    value = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    display_value = models.TextField(blank=True, null=True)
    service_lab_group = models.ForeignKey(LabGroup, on_delete=models.SET_NULL, related_name='favourite_service_lab_group_metadata_options', blank=True, null=True)
    lab_group = models.ForeignKey(LabGroup, on_delete=models.SET_NULL, related_name='favourite_lab_group_metadata_options', blank=True, null=True)
    preset = models.ForeignKey(Preset, on_delete=models.SET_NULL, related_name='favourite_metadata_options', blank=True, null=True)
    is_global = models.BooleanField(default=False)

    class Meta:
        app_label = 'cc'
        ordering = ['id']

class MetadataTableTemplate(models.Model):
    history = HistoricalRecords()
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name='metadata_table_templates', blank=True, null=True)
    name = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    user_columns = models.ManyToManyField(MetadataColumn, related_name='metadata_table_templates', blank=True)
    staff_columns = models.ManyToManyField(MetadataColumn, related_name='assigned_metadata_table_templates', blank=True)
    service_lab_group = models.ForeignKey(LabGroup, on_delete=models.SET_NULL, related_name='service_lab_group_metadata_table_templates', blank=True, null=True)
    lab_group = models.ForeignKey(LabGroup, on_delete=models.SET_NULL, related_name='lab_group_metadata_table_templates', blank=True, null=True)
    enabled = models.BooleanField(default=True)
    field_mask_mapping = models.TextField(blank=True, null=True)

    class Meta:
        app_label = 'cc'
        ordering = ['id']

class ExternalContactDetails(models.Model):
    history = HistoricalRecords()
    contact_method_alt_name = models.CharField(max_length=255, blank=False, null=False)
    contact_type_choices = [
        ("email", "Email"),
        ("phone", "Phone"),
        ("address", "Address"),
        ("other", "Other"),
    ]
    contact_type = models.CharField(max_length=20, choices=contact_type_choices, default="email")
    contact_value = models.TextField(blank=False, null=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "cc"
        ordering = ["id"]

class ExternalContact(models.Model):
    history = HistoricalRecords()
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="external_contact_details", blank=True, null=True)
    contact_name = models.CharField(max_length=255, blank=False, null=False)
    contact_details = models.ManyToManyField(ExternalContactDetails, blank=True, related_name="external_contact")

    class Meta:
        app_label = "cc"
        ordering = ["id"]


class SupportInformation(models.Model):
    history = HistoricalRecords()
    vendor_name = models.CharField(max_length=255, blank=True, null=True)
    vendor_contacts = models.ManyToManyField("ExternalContact", blank=True, related_name="vendor_contact")
    manufacturer_name = models.CharField(max_length=255, blank=True, null=True)
    manufacturer_contacts = models.ManyToManyField("ExternalContact", blank=True, related_name="manufacturer_contact")
    serial_number = models.TextField(blank=True, null=True)
    maintenance_frequency_days = models.IntegerField(blank=True, null=True)
    location = models.ForeignKey("StorageObject", on_delete=models.SET_NULL, blank=True, related_name="instrument_location", null=True)
    warranty_start_date = models.DateField(blank=True, null=True)
    warranty_end_date = models.DateField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "cc"
        ordering = ["id"]

class MaintenanceLog(models.Model):
    history = HistoricalRecords()
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="maintenance_logs")
    maintenance_date = models.DateTimeField(blank=False, null=False)
    maintenance_type_choices = [
        ("routine", "Routine"),
        ("emergency", "Emergency"),
        ("other", "Other"),
        ]
    maintenance_type = models.CharField(max_length=20, choices=maintenance_type_choices, default="routine")
    maintenance_description = models.TextField(blank=True, null=True)
    maintenance_notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="maintenance_logs", blank=True, null=True)
    status_choices = [
        ("completed", "Completed"),
        ("pending", "Pending"),
        ("in_progress", "In Progress"),
        ("requested", "Requested"),
        ("cancelled", "Cancelled"),
    ]
    is_template = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=status_choices, default="pending")
    annotation_folder = models.ForeignKey("AnnotationFolder", on_delete=models.SET_NULL,
                                          related_name="maintenance_logs", blank=True, null=True)

    class Meta:
        app_label = "cc"
        ordering = ["id"]

    def create_default_folders(self):
        if self.annotation_folder:
            return

        folder = AnnotationFolder.objects.create(
            folder_name=f"Maintenance {self.id} - {self.maintenance_date.strftime('%Y-%m-%d')}",
            instrument=self.instrument,
        )
        self.annotation_folder = folder
        self.save()


class MessageThread(models.Model):
    """Group related messages together in conversations"""
    title = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    participants = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="message_threads", blank=True)
    is_system_thread = models.BooleanField(default=False)
    lab_group = models.ForeignKey("LabGroup", on_delete=models.CASCADE, related_name="message_threads", blank=True,
                                  null=True)
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="created_threads", blank=True,
                                null=True)

    class Meta:
        app_label = "cc"
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title or f"Thread {self.id}"


class Message(models.Model):
    """Individual message content"""
    thread = models.ForeignKey(MessageThread, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name="sent_messages",
                               blank=True, null=True)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    TYPE_CHOICES = [
        ("user_message", "User Message"),
        ("system_notification", "System Notification"),
        ("alert", "Alert"),
        ("announcement", "Announcement"),
    ]
    message_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default="user_message")

    PRIORITY_CHOICES = [
        ("low", "Low"),
        ("normal", "Normal"),
        ("high", "High"),
        ("urgent", "Urgent"),
    ]
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="normal")

    project = models.ForeignKey("Project", on_delete=models.SET_NULL, related_name="messages", blank=True, null=True)
    protocol = models.ForeignKey("ProtocolModel", on_delete=models.SET_NULL, related_name="messages", blank=True,
                                 null=True)
    session = models.ForeignKey("Session", on_delete=models.SET_NULL, related_name="messages", blank=True, null=True)
    instrument = models.ForeignKey("Instrument", on_delete=models.SET_NULL, related_name="messages", blank=True,
                                   null=True)
    instrument_job = models.ForeignKey("InstrumentJob", on_delete=models.SET_NULL, related_name="messages", blank=True,
                                       null=True)
    stored_reagent = models.ForeignKey("StoredReagent", on_delete=models.SET_NULL, related_name="messages", blank=True,
                                       null=True)

    expires_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        app_label = "cc"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.get_message_type_display()} from {self.sender or 'System'}"

    @property
    def is_expired(self):
        if self.expires_at:
            return timezone.now() > self.expires_at
        return False


class MessageRecipient(models.Model):
    """Tracks message status for each recipient"""
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="recipients")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="received_messages")
    read_at = models.DateTimeField(blank=True, null=True)
    is_read = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        app_label = "cc"
        ordering = ["-message__created_at"]
        unique_together = ['message', 'user']

    def __str__(self):
        return f"{self.user} - {self.message}"

    def mark_as_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save()


class MessageAttachment(models.Model):
    """Files attached to messages"""
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to="message_attachments/")
    file_name = models.CharField(max_length=255)
    file_size = models.IntegerField()
    content_type = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "cc"
        ordering = ["id"]

    def __str__(self):
        return self.file_name


class SiteSettings(models.Model):
    """Site-wide configuration settings"""
    history = HistoricalRecords()
    
    # Singleton pattern - only one instance should exist
    is_active = models.BooleanField(default=True)
    
    # Branding settings
    site_name = models.CharField(max_length=255, default="CUPCAKE", help_text="Name displayed in the application")
    site_tagline = models.CharField(max_length=500, blank=True, null=True, help_text="Tagline or description")
    
    # Visual branding
    logo = models.ImageField(upload_to="site_settings/logos/", blank=True, null=True, help_text="Site logo")
    favicon = models.ImageField(upload_to="site_settings/favicons/", blank=True, null=True, help_text="Site favicon")
    
    # Banner settings
    banner_enabled = models.BooleanField(default=False, help_text="Enable site-wide banner")
    banner_text = models.TextField(blank=True, null=True, help_text="Banner message text")
    banner_color = models.CharField(max_length=7, default="#0066cc", help_text="Banner background color (hex)")
    banner_text_color = models.CharField(max_length=7, default="#ffffff", help_text="Banner text color (hex)")
    banner_dismissible = models.BooleanField(default=True, help_text="Allow users to dismiss banner")
    
    # Theme settings
    primary_color = models.CharField(max_length=7, default="#0066cc", help_text="Primary theme color (hex)")
    secondary_color = models.CharField(max_length=7, default="#6c757d", help_text="Secondary theme color (hex)")
    
    # Footer settings
    footer_text = models.TextField(blank=True, null=True, help_text="Custom footer text")
    
    # Import restrictions - Control what users can import
    allow_import_protocols = models.BooleanField(default=True, help_text="Allow users to import protocol data")
    allow_import_sessions = models.BooleanField(default=True, help_text="Allow users to import session data")
    allow_import_annotations = models.BooleanField(default=True, help_text="Allow users to import annotation data")
    allow_import_projects = models.BooleanField(default=True, help_text="Allow users to import project data")
    allow_import_reagents = models.BooleanField(default=True, help_text="Allow users to import reagent and storage data")
    allow_import_instruments = models.BooleanField(default=True, help_text="Allow users to import instrument data")
    allow_import_lab_groups = models.BooleanField(default=True, help_text="Allow users to import lab group data")
    allow_import_messaging = models.BooleanField(default=False, help_text="Allow users to import messaging data")
    allow_import_support_models = models.BooleanField(default=True, help_text="Allow users to import metadata and support models")
    
    # Advanced import settings
    staff_only_import_override = models.BooleanField(default=False, help_text="Only staff users can override import restrictions")
    import_archive_size_limit_mb = models.PositiveIntegerField(default=500, help_text="Maximum size of import archive in MB (0 = no limit)")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="site_settings_updates")
    
    class Meta:
        app_label = "cc"
        verbose_name = "Site Settings"
        verbose_name_plural = "Site Settings"
        ordering = ["-updated_at"]
    
    def __str__(self):
        return f"Site Settings - {self.site_name}"
    
    def save(self, *args, **kwargs):
        # Singleton pattern - ensure only one active instance
        if self.is_active:
            SiteSettings.objects.filter(is_active=True).exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)
    
    @classmethod
    def get_current(cls):
        """Get the current active site settings"""
        return cls.objects.filter(is_active=True).first()
    
    @classmethod
    def get_or_create_default(cls):
        """Get current settings or create default if none exist"""
        settings_obj = cls.get_current()
        if not settings_obj:
            settings_obj = cls.objects.create(is_active=True)
        return settings_obj
    
    def get_allowed_import_options(self, user=None):
        """
        Get the import options allowed by site settings, optionally considering user permissions
        
        Args:
            user: Optional User instance to check for staff override permissions
            
        Returns:
            dict: Dictionary of allowed import options
        """
        # Check if staff can override restrictions
        if user and user.is_staff and self.staff_only_import_override:
            # Staff users can import everything if override is enabled
            return {
                'protocols': True,
                'sessions': True,
                'annotations': True,
                'projects': True,
                'reagents': True,
                'instruments': True,
                'lab_groups': True,
                'messaging': True,
                'support_models': True
            }
        
        # Return settings based on site configuration
        return {
            'protocols': self.allow_import_protocols,
            'sessions': self.allow_import_sessions,
            'annotations': self.allow_import_annotations,
            'projects': self.allow_import_projects,
            'reagents': self.allow_import_reagents,
            'instruments': self.allow_import_instruments,
            'lab_groups': self.allow_import_lab_groups,
            'messaging': self.allow_import_messaging,
            'support_models': self.allow_import_support_models
        }
    
    def filter_import_options(self, requested_options, user=None):
        """
        Filter requested import options against site settings
        
        Args:
            requested_options: Dict of requested import options
            user: Optional User instance to check for staff override permissions
            
        Returns:
            dict: Filtered import options that comply with site settings
        """
        allowed_options = self.get_allowed_import_options(user)
        
        # If no specific options requested, return all allowed options
        if not requested_options:
            return allowed_options
        
        # Filter requested options against allowed options
        filtered_options = {}
        for key, value in requested_options.items():
            if key in allowed_options:
                # Only allow if both requested and site setting allow it
                filtered_options[key] = value and allowed_options[key]
            else:
                # Unknown option, default to False
                filtered_options[key] = False
        
        return filtered_options


class DocumentPermission(models.Model):
    """Granular permissions for shared documents (annotations with file type) and folders"""
    history = HistoricalRecords()
    
    PERMISSION_CHOICES = [
        ('view', 'View'),
        ('download', 'Download'),
        ('comment', 'Comment'),
        ('edit', 'Edit'),
        ('share', 'Share'),
        ('delete', 'Delete'),
    ]

    annotation = models.ForeignKey('Annotation', on_delete=models.CASCADE, related_name='document_permissions', null=True, blank=True)

    folder = models.ForeignKey('AnnotationFolder', on_delete=models.CASCADE, related_name='folder_permissions', null=True, blank=True)

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True)
    lab_group = models.ForeignKey('LabGroup', on_delete=models.CASCADE, null=True, blank=True)

    can_view = models.BooleanField(default=True)
    can_download = models.BooleanField(default=True)
    can_comment = models.BooleanField(default=False)
    can_edit = models.BooleanField(default=False)
    can_share = models.BooleanField(default=False)
    can_delete = models.BooleanField(default=False)

    shared_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='shared_documents')
    shared_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True, help_text="Optional expiration date for access")

    last_accessed = models.DateTimeField(null=True, blank=True)
    access_count = models.PositiveIntegerField(default=0)
    
    class Meta:
        app_label = "cc"
        unique_together = [
            ('annotation', 'user'),
            ('annotation', 'lab_group'),
            ('folder', 'user'),
            ('folder', 'lab_group'),
        ]
        indexes = [
            models.Index(fields=['annotation', 'user']),
            models.Index(fields=['annotation', 'lab_group']),
            models.Index(fields=['folder', 'user']),
            models.Index(fields=['folder', 'lab_group']),
        ]
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(annotation__isnull=False, folder__isnull=True) |
                    models.Q(annotation__isnull=True, folder__isnull=False)
                ),
                name='document_permission_either_annotation_or_folder'
            ),
            models.CheckConstraint(
                check=(
                    models.Q(user__isnull=False, lab_group__isnull=True) |
                    models.Q(user__isnull=True, lab_group__isnull=False)
                ),
                name='document_permission_either_user_or_lab_group'
            )
        ]
    
    def __str__(self):
        target = self.user.username if self.user else f"Lab Group: {self.lab_group.name}"
        if self.annotation:
            return f"Document Permission: {self.annotation.annotation_name or 'Unnamed'} -> {target}"
        elif self.folder:
            return f"Folder Permission: {self.folder.folder_name} -> {target}"
        else:
            return f"Permission: Unknown target -> {target}"
    
    def is_expired(self):
        """Check if the permission has expired"""
        if self.expires_at:
            from django.utils import timezone
            return timezone.now() > self.expires_at
        return False
    
    def record_access(self):
        """Record an access to this document"""
        from django.utils import timezone
        self.last_accessed = timezone.now()
        self.access_count += 1
        self.save(update_fields=['last_accessed', 'access_count'])
    
    @classmethod
    def user_can_access(cls, annotation, user, permission_type='view'):
        """Check if user can access annotation with specific permission"""
        if not annotation.file:
            return False  # Not a document
            
        # Owner always has full access
        if annotation.user == user:
            return True
            
        # Check direct user permissions
        user_perm = cls.objects.filter(annotation=annotation, user=user).first()
        if user_perm and not user_perm.is_expired():
            return getattr(user_perm, f'can_{permission_type}', False)
        
        # Check lab group permissions
        user_groups = user.lab_groups.all()
        for group in user_groups:
            group_perm = cls.objects.filter(annotation=annotation, lab_group=group).first()
            if group_perm and not group_perm.is_expired():
                return getattr(group_perm, f'can_{permission_type}', False)
        
        return False
    
    @classmethod
    def user_can_access_folder(cls, folder, user, permission_type='view'):
        """Check if user can access folder with specific permission"""
        # Owner always has full access
        if folder.owner == user:
            return True
            
        # Check direct folder permissions
        user_perm = cls.objects.filter(folder=folder, user=user).first()
        if user_perm and not user_perm.is_expired():
            return getattr(user_perm, f'can_{permission_type}', False)
        
        # Check lab group permissions
        user_groups = user.lab_groups.all()
        for group in user_groups:
            group_perm = cls.objects.filter(folder=folder, lab_group=group).first()
            if group_perm and not group_perm.is_expired():
                return getattr(group_perm, f'can_{permission_type}', False)
        
        # Check parent folder permissions (inheritance)
        if folder.parent_folder:
            return cls.user_can_access_folder(folder.parent_folder, user, permission_type)
        
        return False
    
    @classmethod
    def user_can_access_annotation_with_folder_inheritance(cls, annotation, user, permission_type='view'):
        """Check if user can access annotation with specific permission, including folder inheritance"""
        if not annotation.file:
            return False  # Not a document
            
        # Owner always has full access
        if annotation.user == user:
            return True
            
        # Check direct annotation permissions first
        user_perm = cls.objects.filter(annotation=annotation, user=user).first()
        if user_perm and not user_perm.is_expired():
            return getattr(user_perm, f'can_{permission_type}', False)
        
        # Check lab group permissions for annotation
        user_groups = user.lab_groups.all()
        for group in user_groups:
            group_perm = cls.objects.filter(annotation=annotation, lab_group=group).first()
            if group_perm and not group_perm.is_expired():
                return getattr(group_perm, f'can_{permission_type}', False)
        
        # Check folder permissions (inheritance from folder hierarchy)
        if annotation.folder:
            return cls.user_can_access_folder(annotation.folder, user, permission_type)
        
        return False
    
    def clean(self):
        """Validate that either annotation or folder is set, but not both"""
        from django.core.exceptions import ValidationError
        
        if not self.annotation and not self.folder:
            raise ValidationError("Either annotation or folder must be specified")
        
        if self.annotation and self.folder:
            raise ValidationError("Cannot specify both annotation and folder")
            
        if not self.user and not self.lab_group:
            raise ValidationError("Either user or lab_group must be specified")
            
        if self.user and self.lab_group:
            raise ValidationError("Cannot specify both user and lab_group")
            
        # Validate annotation has file if specified
        if self.annotation and not self.annotation.file:
            raise ValidationError("Can only set permissions on annotations with files")
            
        # Validate folder is shared document folder if specified
        if self.folder and not self.folder.is_shared_document_folder:
            raise ValidationError("Can only set permissions on shared document folders")
    
    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class BackupLog(models.Model):
    """Track backup operations for monitoring and logging"""
    history = HistoricalRecords()
    
    BACKUP_TYPE_CHOICES = [
        ('database', 'Database Backup'),
        ('media', 'Media Backup'),
        ('full', 'Full Backup'),
    ]
    
    STATUS_CHOICES = [
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]
    
    backup_type = models.CharField(max_length=20, choices=BACKUP_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='running')
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True, help_text="Backup duration in seconds")
    
    # File information
    backup_file_path = models.TextField(null=True, blank=True, help_text="Path to backup file")
    file_size_bytes = models.BigIntegerField(null=True, blank=True, help_text="Backup file size in bytes")
    
    # Status information
    error_message = models.TextField(null=True, blank=True, help_text="Error details if backup failed")
    success_message = models.TextField(null=True, blank=True, help_text="Success details")
    
    # Metadata
    triggered_by = models.CharField(max_length=100, default='cron', help_text="What triggered the backup (cron, manual, etc.)")
    container_id = models.CharField(max_length=64, null=True, blank=True, help_text="Docker container ID that ran the backup")
    
    class Meta:
        app_label = "cc"
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['backup_type', 'status']),
            models.Index(fields=['started_at']),
        ]
    
    def __str__(self):
        return f"{self.get_backup_type_display()} - {self.get_status_display()} at {self.started_at}"
    
    @property
    def file_size_mb(self):
        """Return file size in MB"""
        if self.file_size_bytes:
            return round(self.file_size_bytes / (1024 * 1024), 2)
        return None
    
    def mark_completed(self, file_path=None, file_size=None, success_message=None):
        """Mark backup as completed"""
        from django.utils import timezone
        self.status = 'completed'
        self.completed_at = timezone.now()
        if self.started_at:
            duration = self.completed_at - self.started_at
            self.duration_seconds = int(duration.total_seconds())
        if file_path:
            self.backup_file_path = file_path
        if file_size:
            self.file_size_bytes = file_size
        if success_message:
            self.success_message = success_message
        self.save()
    
    def mark_failed(self, error_message):
        """Mark backup as failed"""
        from django.utils import timezone
        self.status = 'failed'
        self.completed_at = timezone.now()
        if self.started_at:
            duration = self.completed_at - self.started_at
            self.duration_seconds = int(duration.total_seconds())
        self.error_message = error_message
        self.save()


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_auth_token(sender, instance=None, created=False, **kwargs):
    if created:
        Token.objects.create(user=instance)

@receiver(post_save, sender=ProtocolModel)
def create_protocol_hash(sender, instance=None, created=False, **kwargs):
    if created:
        instance.model_hash = instance.calculate_protocol_hash()
        instance.save()

@receiver(post_save, sender=Instrument)
def create_instrument_annotation_folders(sender, instance=None, created=False, **kwargs):
    if created:
        instance.create_default_folders()

@receiver(post_save, sender=StoredReagent)
def create_stored_reagent_annotation_folders(sender, instance=None, created=False, **kwargs):
    if created:
        instance.create_default_folders()

@receiver(post_save, sender=MaintenanceLog)
def create_maintenance_log_folders(sender, instance=None, created=False, **kwargs):
    if created:
        instance.create_default_folders()

@receiver(post_save, sender=ReagentAction)
def check_reagent_stock_after_action(sender, instance=None, created=False, **kwargs):
    if instance and instance.reagent:
        instance.reagent.check_low_stock()
        instance.reagent.check_expiration()

@receiver(post_save, sender=StoredReagent)
def create_owner_subscription(sender, instance=None, created=False, **kwargs):
    if created and instance.user:
        instance.subscribe_user(
            user=instance.user,
            notify_low_stock=instance.notify_on_low_stock,
            notify_expiry=instance.notify_on_expiry
        )


@receiver(post_save, sender=TimeKeeper)
def notify_timekeeper_changes(sender, instance=None, created=False, **kwargs):
    """Send notifications when a TimeKeeper is created or updated"""

    if not instance:
        return

    if created:
        action = "started"
        title = f"Timer Started: {instance.step.step_description if instance.step else 'Session Timer'}"
    else:
        action = "updated"
        title = f"Timer Updated: {instance.step.step_description if instance.step else 'Session Timer'}"

    notification_data = {
        "type": "timer_notification",
        "action": action,
        "title": title,
        "timer_id": instance.id,
        "started": instance.started,
        "current_duration": instance.current_duration or 0,
        "timestamp": timezone.now().isoformat()
    }

    if instance.session:
        notification_data["session_id"] = str(instance.session.unique_id)
        notification_data["session_name"] = instance.session.name or f"Session {instance.session.id}"

    if instance.step:
        notification_data["step_id"] = instance.step.id
        notification_data["step_description"] = instance.step.step_description

    channel_layer = get_channel_layer()

    users_to_notify = set()

    users_to_notify.add(instance.user.id)

    if instance.session:
        users_to_notify.add(instance.session.user.id)

        for editor in instance.session.editors.all():
            users_to_notify.add(editor.id)
        for viewer in instance.session.viewers.all():
            users_to_notify.add(viewer.id)

    for user_id in users_to_notify:
        async_to_sync(channel_layer.group_send)(
            f"user_{user_id}_notifications",
            {
                "type": "notification_message",
                "message": notification_data
            }
        )