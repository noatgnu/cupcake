from datetime import datetime
import hashlib
import requests
from bs4 import BeautifulSoup
from django.core import signing
from django.db import models, transaction
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from rest_framework.authtoken.models import Token
from cc.utils import default_columns

# Create your models here.

class Project(models.Model):
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
        hash_object.update(self.protocol_title.encode())
        hash_object.update(self.protocol_description.encode())
        for step in self.steps.all():
            hash_object.update(step.step_description.encode())
            hash_object.update(str(step.step_duration).encode())
            if step.step_section:
                hash_object.update(step.step_section.section_description.encode())
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


    def sync_session_upstream(self, upstream_node_url: str):
        """
        Sync session with upstream node
        :param upstream_node_url:
        :return:
        """


class Instrument(models.Model):
    instrument_name = models.TextField(blank=False, null=False)
    instrument_description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    enabled = models.BooleanField(default=True)
    remote_id = models.BigIntegerField(blank=True, null=True)
    remote_host = models.ForeignKey("RemoteHost", on_delete=models.CASCADE, related_name="instruments", blank=True, null=True)


class InstrumentUsage(models.Model):
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


class InstrumentPermission(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="instrument_permissions")
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="instrument_permissions")
    can_view = models.BooleanField(default=False)
    can_book = models.BooleanField(default=False)
    can_manage = models.BooleanField(default=False)


class Annotation(models.Model):
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="annotations", blank=True, null=True)
    step = models.ForeignKey(ProtocolStep, on_delete=models.CASCADE, related_name="annotations", blank=True, null=True)
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

    def __repr__(self):
        return self.annotation

    def delete(self, using=None, keep_parents=False):
        if self.file:
            self.file.delete()
        super(Annotation, self).delete(using=using, keep_parents=keep_parents)

class AnnotationFolder(models.Model):
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="annotation_folders")
    folder_name = models.TextField(blank=False, null=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    parent_folder = models.ForeignKey("self", on_delete=models.CASCADE, related_name="child_folders", blank=True, null=True)
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
    start_time = models.DateTimeField(auto_now=True)
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="time_keeper")
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
    name = models.CharField(max_length=255)
    unit = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class ProtocolReagent(models.Model):
    protocol = models.ForeignKey(ProtocolModel, on_delete=models.CASCADE, related_name="reagents")
    reagent = models.ForeignKey(Reagent, on_delete=models.CASCADE)
    quantity = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remote_id = models.BigIntegerField(blank=True, null=True)


class StepReagent(models.Model):
    step = models.ForeignKey(ProtocolStep, on_delete=models.CASCADE, related_name="reagents")
    reagent = models.ForeignKey(Reagent, on_delete=models.CASCADE)
    quantity = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    scalable = models.BooleanField(default=False)
    scalable_factor = models.FloatField(default=1.0)
    remote_id = models.BigIntegerField(blank=True, null=True)

class Tag(models.Model):
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



class StoredReagent(models.Model):
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


class ReagentAction(models.Model):
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
    mandatory = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['column_position']
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
    injection_unit = models.TextField(blank=True, null=True)
    search_engine = models.TextField(blank=True, null=True)
    search_engine_version = models.TextField(blank=True, null=True)
    search_details = models.TextField(blank=True, null=True)
    location = models.TextField(blank=True, null=True)
    stored_reagent = models.ForeignKey(StoredReagent, on_delete=models.SET_NULL, related_name='instrument_jobs', blank=True, null=True)

    class Meta:
        app_label = 'cc'
        ordering = ['id']

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_auth_token(sender, instance=None, created=False, **kwargs):
    if created:
        Token.objects.create(user=instance)

@receiver(post_save, sender=ProtocolModel)
def create_protocol_hash(sender, instance=None, created=False, **kwargs):
    if created:
        instance.model_hash = instance.calculate_protocol_hash()
        instance.save()