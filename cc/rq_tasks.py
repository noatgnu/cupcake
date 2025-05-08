import base64
import datetime
import io
import json
import shutil
import threading
import uuid
from datetime import time, timedelta
import csv
import ffmpeg
import pandas as pd
import webvtt
from PIL import Image
from asgiref.sync import async_to_sync
from bs4 import BeautifulSoup
from channels.layers import get_channel_layer
from django.contrib.auth.models import User
from django.core.files import File
from django.core.management import call_command
from django.core.signing import TimestampSigner
from django.db.models import Q, QuerySet
from django.utils import timezone
from django_rq import job
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls
from drf_chunked_upload.models import ChunkedUpload
from openpyxl.reader.excel import load_workbook
from openpyxl.styles import PatternFill, Border, Side, Alignment
from openpyxl.utils import get_column_letter
from openpyxl.workbook import Workbook
from openpyxl.worksheet.datavalidation import DataValidation
from pytesseract import pytesseract
from sdrf_pipelines.sdrf.sdrf import SdrfDataFrame

from cc.models import Annotation, ProtocolModel, ProtocolStep, StepVariation, ProtocolSection, Session, \
    AnnotationFolder, Reagent, ProtocolReagent, StepReagent, ProtocolTag, StepTag, Tag, Project, MetadataColumn, \
    InstrumentJob, SubcellularLocation, Species, MSUniqueVocabularies, Unimod, FavouriteMetadataOption, InstrumentUsage, \
    LabGroup, Tissue, StorageObject, ReagentAction, StoredReagent
from django.conf import settings
import numpy as np
import subprocess
import os
import select
from cc.serializers import AnnotationSerializer, ProtocolModelSerializer, ProtocolSectionSerializer, \
    StepVariationSerializer, ProtocolStepSerializer, SessionSerializer, AnnotationFolderSerializer, \
    ReagentSerializer, ProtocolReagentSerializer, StepReagentSerializer, TagSerializer, ProtocolTagSerializer, \
    StepTagSerializer, ProjectSerializer
import docx
import re

from docx.shared import Inches, RGBColor
import re

from cc.utils import user_metadata, staff_metadata, required_metadata_name, identify_barcode_format

capture_language = re.compile(r"auto-detected language: (\w+)")

@job('transcribe', timeout='1h')
def transcribe_audio(audio_path: str, model_path: str, step_annotation_id: int, language: str = "auto", translate: bool = False, custom_id: str = None):
    """
    Convert audio from webm to wav using ffmpeg, then store the wave file as temporary file and transcribe it using the whisper model using subprocess and whispercpp main binary and base.en model before deleting the temporary file
    :param audio_path:
    :param model_path:
    :param step_annotation_id:
    :return:
    """

    # Convert audio from webm to wav using ffmpeg
    wav_path = audio_path.replace(".webm", ".wav")
    #ffmpeg.input(audio_path).output(wav_path, format="s16le", acodec="pcm_s16le", ac=1, ar=44100).run(cmd=['ffmpeg', '-nostdin'], capture_stdout=True, capture_stderr=True)
    subprocess.run(["ffmpeg", "-y", "-i", audio_path, "-vn", "-ar", "16000", wav_path])
    # Transcribe audio using whisper model
    whispercpp_bin_path = settings.WHISPERCPP_PATH
    temporary_vtt_path = wav_path + ".vtt"
    thread_count = settings.WHISPERCPP_THREAD_COUNT
    # Run whispercpp binary
    print(f"Running whispercpp binary: {whispercpp_bin_path} -m {model_path} -f {wav_path} -ovtt -t {thread_count}")
    cmd = ['stdbuf', '-oL', whispercpp_bin_path, "-m", model_path, "-f", wav_path, "-ovtt", '-t', thread_count, '-l', language]
    #if translate:
    #    cmd.append("-tr")
    #process = subprocess.run(cmd)
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    # capture whisper detected language

    annotation = Annotation.objects.get(id=step_annotation_id)
    for line in process.stdout:
        line = line.decode("utf-8")
        print(line)
        if "auto-detected language" in line:
            s = capture_language.search(line)
            if s:
                annotation.language = s.group(1)
    if not annotation.language:
        for line in process.stderr:
            line = line.decode("utf-8")
            print(line)
            if "auto-detected language" in line:
                s = capture_language.search(line)
                if s:
                    annotation.language = s.group(1)

    #for line in process.stderr.decode("utf-8").split("\n"):
    #    print(f"stderr: {line}")
    with open(temporary_vtt_path, "rt") as f:
        annotation.transcription = f.read()
        annotation.transcribed = True
        annotation.save()

    if translate:
        if annotation.language and annotation.language != "en":
            print("Translating from" + annotation.language + " to en")
            cmd.append("-tr")
            process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            with open(temporary_vtt_path, "rt") as f:
                annotation.translation = f.read()
    annotation.save()

    os.remove(wav_path)
    os.remove(temporary_vtt_path)
    session_id = annotation.session.unique_id
    channel_layer = get_channel_layer()
    data = AnnotationSerializer(annotation, many=False).data

    async_to_sync(channel_layer.group_send)(
        f"transcription_{session_id}",
        {
            "type": "transcription_message",
            "message": data,
        },
    )
    return annotation.transcription





@job('transcribe', timeout='1h')
def transcribe_audio_from_video(video_path: str, model_path: str, step_annotation_id: int, language: str = "auto", translate: bool = False, custom_id: str = None):
    """
    Convert audio from webm video to wav using ffmpeg, then store the wave file as temporary file and transcribe it using the whisper model using subprocess and whispercpp main binary and base.en model before deleting the temporary file
    :param video_path:
    :param model_path:
    :param step_annotation_id:
    :return:
    """

    # Convert audio from webm video to wav using ffmpeg specify the kHz to 16 kHz
    wav_path = video_path.replace(".webm", ".wav")
    #ffmpeg.input(video_path).output(wav_path, format="s16le", acodec="pcm_s16le", ac=1, ar=44100).run(cmd=['ffmpeg', '-nostdin'], capture_stdout=True, capture_stderr=True)
    #subprocess.run(["ffmpeg", "-i", video_path, "-vn", "-ar", "44100", wav_path])
    subprocess.run(["ffmpeg", "-y", "-i", video_path, "-vn", "-ar", "16000", wav_path])
    # Transcribe audio using whisper model
    whispercpp_bin_path = settings.WHISPERCPP_PATH
    temporary_vtt_path = wav_path+".vtt"
    thread_count = settings.WHISPERCPP_THREAD_COUNT
    # Run whispercpp binary
    print(f"Running whispercpp binary: {whispercpp_bin_path} -m {model_path} -f {wav_path} -ovtt -t {thread_count}")
    cmd = [whispercpp_bin_path, "-m", model_path, "-f", wav_path, "-ovtt", '-t', thread_count, '-l', language]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    # capture whisper detected language

    annotation = Annotation.objects.get(id=step_annotation_id)
    for line in process.stdout:
        line = line.decode("utf-8")
        print(line)
        if "auto-detected language" in line:
            s = capture_language.search(line)
            if s:
                annotation.language = s.group(1)
    if not annotation.language:
        for line in process.stderr:
            line = line.decode("utf-8")
            print(line)
            if "auto-detected language" in line:
                s = capture_language.search(line)
                if s:
                    annotation.language = s.group(1)

    with open(temporary_vtt_path, "rt") as f:
        annotation.transcription = f.read()
        annotation.transcribed = True

    if translate:
        if annotation.language and annotation.language != "en":
            print("Translating from" + annotation.language + " to en")
            cmd.append("-tr")
            process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            with open(temporary_vtt_path, "rt") as f:
                annotation.translation = f.read()

    annotation.save()

    os.remove(wav_path)
    os.remove(temporary_vtt_path)
    session_id = annotation.session.unique_id
    channel_layer = get_channel_layer()
    data = AnnotationSerializer(annotation, many=False).data
    async_to_sync(channel_layer.group_send)(
        f"transcription_{session_id}",
        {
            "type": "transcription_message",
            "message": data,
        },
    )
    return annotation.transcription

@job('export', timeout='1h')
def create_docx(protocol_id: int, session_id: str = None, user_id: int = None, instance_id: str = None):
    protocol = ProtocolModel.objects.get(id=protocol_id)
    doc = docx.Document()
    doc.add_heading(remove_html_tags(protocol.protocol_title), level=1)
    html_to_docx(protocol.protocol_description, doc)
    for section in protocol.get_section_in_order():
        doc.add_heading(remove_html_tags(section.section_description), level=2)
        for n, step in enumerate(section.get_step_in_order()):
            # add divider between steps
            doc.add_paragraph("----------------------------------------------------")
            doc.add_paragraph(f"Step {n+1}")
            description = step.step_description
            for reagent in step.reagents.all():
                for i in [f"{reagent.id}.name", f"{reagent.id}.quantity", f"{reagent.id}.unit", f"{reagent.id}.scaled_quantity"]:
                    if i in description:
                        if i == f"{reagent.id}.scaled_quantity":
                            description = description.replace(i, str(reagent.quantity * reagent.scalable_factor))
                        elif i == f"{reagent.id}.quantity":
                            description = description.replace(i, str(reagent.quantity))
                        elif i == f"{reagent.id}.unit":
                            description = description.replace(i, reagent.reagent.unit)
                        else:
                            description = description.replace(i, reagent.reagent.name)

            html_to_docx(step.step_description, doc)
            doc.add_paragraph(f"(Duration:{convert_seconds_to_time(step.step_duration)})")
            session = None
            if session_id:
                session = protocol.sessions.get(unique_id=session_id)
            # else:
            #
            #     session = protocol.sessions.all()
            #     if session:
            #         session = session[0]
            #     else:
            #         session = None
            annotations = None
            if session:
                annotations = step.annotations.filter(session=session)

            if annotations:
                for annotation in step.annotations.all():
                    doc.add_paragraph(f"Annotation: {annotation.annotation_type}")
                    if annotation.transcribed:
                        doc.add_paragraph("Transcription:")
                        if annotation.transcription.startswith("WEBVTT"):
                            for i in webvtt.read_buffer(io.StringIO(annotation.transcription)):
                                doc.add_paragraph(f"({i.start} - {i.end}) {i.text}")

                    if annotation.translation:
                        doc.add_paragraph("Translation:")
                        if annotation.translation.startswith("WEBVTT"):
                            for i in webvtt.read_buffer(io.StringIO(annotation.translation)):
                                doc.add_paragraph(f"({i.start} - {i.end}) {i.text}")
                    if annotation.summary:
                        doc.add_paragraph("Summary:")
                        doc.add_paragraph(annotation.summary)

                    # if annotation has image add it to the document
                    if annotation.annotation_type == "image":
                        #get dimensions of the image and add it to the document with the correct dimensions respecting the original aspect ratio with max width of 4 inches and max height of 6 inches
                        image_dimensions = ffmpeg.probe(annotation.file.path, show_entries="stream=width,height")
                        width = int(image_dimensions["streams"][0]["width"])
                        height = int(image_dimensions["streams"][0]["height"])
                        if width > height:
                            doc.add_picture(annotation.file.path, width=Inches(4))
                        else:
                            doc.add_picture(annotation.file.path, height=Inches(6))
                    if annotation.annotation_type == "sketch":
                        load_json = json.load(annotation.file)
                        #convert base64 image to image file
                        if "png" in load_json:
                            data = load_json["png"].split('base64,')
                            if len(data) > 1:
                                pixel_width = load_json["width"]
                                pixel_height = load_json["height"]
                                image_bytes = base64.b64decode(data[1])
                                image_file = io.BytesIO(image_bytes)
                                doc.add_picture(image_file, width=Inches(pixel_width/pixel_height))
                    if annotation.annotation_type == "table":
                        data = json.loads(annotation.annotation)
                        if data:
                            doc.add_paragraph(data["name"])
                            table = doc.add_table(rows=data["nRow"], cols=data["nCol"])
                            table.style = 'Table Grid'

                            for n, row in enumerate(data["content"]):
                                row_cells = table.rows[n].cells
                                for nc, c in enumerate(row):
                                    row_cells[nc].add_paragraph(c)
                                    if "trackingMap" in data:
                                        # color the cell background blue if cell value is true in trackingMap
                                        if f"{n},{nc}" in data["trackingMap"]:
                                            if data["trackingMap"][f"{n},{nc}"]:
                                                shading_elm = parse_xml(r'<w:shd {} w:fill="0000FF"/>'.format(nsdecls('w')))
                                                row_cells[nc]._tc.get_or_add_tcPr().append(shading_elm)
                    if annotation.annotation_type == "checklist":
                        data = json.loads(annotation.annotation)
                        if data:
                            doc.add_paragraph(data["name"])
                            for n, c in enumerate(data["checkList"]):
                                doc.add_paragraph(f"{n+1}. {c['content'] if 'content' in c else ''} {c['checked'] if 'checked' in c else ''}")
                    if annotation.annotation_type == "alignment":
                        data = json.loads(annotation.annotation)
                        if data:
                            main = data["dataURL"].split('base64,')
                            if len(main) > 1:
                                image_bytes = base64.b64decode(main[1])
                                image_file = io.BytesIO(image_bytes)
                                doc.add_picture(image_file, width=Inches(4))
                            for extracted in data["extractedSegments"]:
                                if "dataURL" in extracted:
                                    data = extracted["dataURL"].split('base64,')
                                    doc.add_paragraph(f"{extracted['start']}-{extracted['end']}")
                                    if len(data) > 1:
                                        image_bytes = base64.b64decode(data[1])
                                        image_file = io.BytesIO(image_bytes)
                                        doc.add_picture(image_file, width=Inches(4))



            # add page break after each section
        doc.add_page_break()
    filename = str(uuid.uuid4())
    docx_filepath = os.path.join(settings.MEDIA_ROOT,"temp", f"{filename}.docx")
    doc.save(docx_filepath)

    signer = TimestampSigner()
    value = signer.sign(f"{filename}.docx")

    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"user_{user_id}",
        {
            "type": "download_message",
            "message": {
                "signed_value": value,
                "user_download": True,
                "instance_id": instance_id
            },
        },
    )
    print(f"Created docx file: {docx_filepath}")
    threading.Timer(60*20, remove_file, args=[docx_filepath]).start()
    return docx_filepath

def remove_file(file_path):
    if os.path.exists(file_path):
        os.remove(file_path)

def remove_html_tags(text):
    clean = re.compile('<.*?>')
    return re.sub(clean, '', text)

def convert_seconds_to_time(seconds):
    second_time = datetime.timedelta(seconds=seconds)
    # convert second to hour, minute, second
    return time(second_time.seconds // 3600, (second_time.seconds // 60) % 60, second_time.seconds % 60).strftime("%H:%M:%S")


def html_to_docx(html, doc: docx.Document):
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup:
        if tag.name == 'p':
            # Create a new paragraph in the docx file
            para = doc.add_paragraph()
            for subtag in tag:
                if subtag.name == 'b':
                    # Add a run with bold style
                    run = para.add_run(subtag.text)
                    run.bold = True
                elif subtag.name == 'i':
                    # Add a run with italic style
                    run = para.add_run(subtag.text)
                    run.italic = True
                elif subtag.name == 'span' and 'style' in subtag.attrs:
                    # Add a run with color style
                    if "rgb" in subtag['style']:
                        color = subtag['style'].split('(')[1].split(')')[0].split(',')
                        r, g, b = int(color[0]), int(color[1]), int(color[2])
                    else:
                        color = subtag['style'].split(':')[1]  # Assuming style="color: #RRGGBB"
                        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
                    run = para.add_run(subtag.text)
                    run.font.color.rgb = RGBColor(r, g, b)
                else:
                    # Add a run with normal style
                    para.add_run(subtag.text)
        else:
            # Add a run with normal style
            doc.add_paragraph(tag.text)

@job('llama', timeout='1h')
def llama_summary(prompt: str, user_id: int, target: dict = None, instance_id: str = None):
    """
    Generate completion using llama model
    :param prompt:
    :param user_id:
    :return:
    """
    llama_bin_path = settings.LLAMA_BIN_PATH
    cmd = [llama_bin_path, "-p", prompt, "-m", settings.LLAMA_DEFAULT_MODEL, "-t", "8", "-c", "2048", "--repeat_penalty", "1.0", "--log-disable", "-n", "4096"]

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    finished = False
    started = False
    for line in process.stdout:
        line = line.decode("utf-8")
        print(line)
        if "<|im_start|>assistant" in line:
            started = True
        if "<|im_end|>" in line and started:
            finished = True
            break
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"user_{user_id}_summary",
            {
                "type": "summary_message",
                "message": {
                    "data": line,
                    "type": "step",
                    "finished": finished,
                    "target": target,
                    "instance_id": instance_id
                },
            },
        )

    if finished:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"user_{user_id}_summary",
            {
                "type": "summary_message",
                "message": {
                    "data": line.split("<|im_end|>")[0],
                    "type": "step",
                    "finished": finished,
                    "target": target,
                    "instance_id": instance_id
                },
            },
        )


@job('llama', timeout='1h')
def llama_summary_transcript(prompt: str, user_id: int, target: dict = None, instance_id: str = None):
    """
    Provide summary from webtt transcript using llama model
    :param prompt:
    :param user_id:
    :param target:
    :return:
    """
    llama_bin_path = settings.LLAMA_BIN_PATH
    cmd = [llama_bin_path, "-p", prompt, "-m", settings.LLAMA_DEFAULT_MODEL, "-t", "8", "-c", "2048", "--repeat_penalty", "1.0", "--log-disable", "-n", "4096"]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    started = False
    finished = False
    for line in process.stdout:
        line = line.decode("utf-8")
        print(line)
        if "<|im_start|>assistant" in line:
            started = True
        if "<|im_end|>" in line and started:
            finished = True
            break
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"user_{user_id}_summary",
            {
                "type": "summary_message",
                "message": {
                    "data": line,
                    "type": "annotation",
                    "finished": finished,
                    "target": target,
                    "instance_id": instance_id
                },
            },
        )
    if finished:
        channel_layer = get_channel_layer()
        annotation = Annotation.objects.get(id=target["annotation"])
        annotation.summary = line.split("<|im_end|>")[0]
        annotation.save()
        async_to_sync(channel_layer.group_send)(
            f"user_{user_id}_summary",
            {
                "type": "summary_message",
                "message": {
                    "data": line.split("<|im_end|>")[0],
                    "type": "annotation",
                    "finished": finished,
                    "target": target,
                    "instance_id": instance_id
                },
            },
        )


@job('ocr', timeout='1h')
def ocr_b64_image(image_b64: str, annotation_id: int, session_id: str, instance_id: str = None):
    """
    Perform OCR on base64 image
    :param image_b64:
    :param user_id:
    :return:
    """

    imgstring = image_b64.split('base64,')[-1].strip()
    image_string = io.BytesIO(base64.b64decode(imgstring))
    image = Image.open(image_string)
    bg = Image.new("RGB", image.size, (255, 255, 255))
    bg.paste(image, image)
    data = pytesseract.image_to_string(bg)
    annotation = Annotation.objects.get(id=annotation_id)
    annotation.transcription = data
    annotation.transcribed = True
    annotation.save()
    print(data)
    data = AnnotationSerializer(annotation, many=False).data
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"transcription_{session_id}",
        {
            "type": "transcription_message",
            "message": data,
        },
    )

@job('export', timeout='3h')
def export_sqlite(user_id:int, session_id: str = None, instance_id: str = None):
    """
    Export user data to sqlite database
    :param user_id:
    :return
    """
    #check if user created this session
    session = Session.objects.get(unique_id=session_id)
    if session.user.id != user_id:
        return
    #create a temporary folder in media temp folder
    media_root = settings.MEDIA_ROOT
    filename = uuid.uuid4().hex
    user_folder = os.path.join(media_root, "temp", filename)
    call_command("export_data_sqlite", session_id, user_folder)
    signer = TimestampSigner()
    value = signer.sign(f"{filename}.cupcake")
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"user_{user_id}",
        {
            "type": "download_message",
            "message": {
                "signed_value": value,
                "user_download": True,
                "instance_id": instance_id
            },
        },
    )

@job('export', timeout='3h')
def export_data(user_id: int, protocol_ids: list[int] = None, instance_id: str = None):
    filename = export_user_data(user_id, protocol_ids=protocol_ids)
    signer = TimestampSigner()
    value = signer.sign(f"{filename}.tar.gz")
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"user_{user_id}",
        {
            "type": "download_message",
            "message": {
                "signed_value": value,
                "user_download": True,
                "instance_id": instance_id
            },
        },
    )

def export_user_data(user_id: int, filename: str = None, protocol_ids: list[int] = None):
    """
    A function that would export user's protocol, protocolstep, annotation, variation, and section data to individual jsons and archive into a tar.gz file
    :param user_id:
    :return:
    """
    user = User.objects.get(id=user_id)
    protocols = ProtocolModel.objects.filter(Q(user=user)|Q(steps__annotations__user=user))
    if protocol_ids:
        protocols = protocols.filter(id__in=protocol_ids)
    print(protocol_ids)
    protocols = protocols.distinct()
    protocolsSteps = ProtocolStep.objects.filter(protocol__in=protocols)
    variations = StepVariation.objects.filter(step__protocol__user=user)
    sections = ProtocolSection.objects.filter(protocol__user=user)
    if protocol_ids:
        sections = sections.filter(protocol__in=protocols)
    sessions = user.sessions.all()
    if protocol_ids:
        sessions = Session.objects.filter(annotations__step__protocol__id__in=protocol_ids).distinct()
    projects = []
    for session in sessions:
        for p in session.projects.filter(owner=user):
            if p not in projects:
                projects.append(p)
    annotations = Annotation.objects.filter(session__user=user)
    folders = AnnotationFolder.objects.filter(session__in=sessions)
    protocol_reagents = ProtocolReagent.objects.filter(protocol__in=protocols)
    step_reagents = StepReagent.objects.filter(step__in=protocolsSteps)
    reagents = Reagent.objects.filter(Q(protocolreagent__in=protocol_reagents) | Q(stepreagent__in=step_reagents))
    protocol_tags = ProtocolTag.objects.filter(protocol__in=protocols)
    step_tags = StepTag.objects.filter(step__in=protocolsSteps)
    tag = Tag.objects.filter(Q(protocoltag__in=protocol_tags) | Q(steptag__in=step_tags))

    protocols_data = ProtocolModelSerializer(protocols, many=True).data
    protocols_steps_data = ProtocolStepSerializer(protocolsSteps, many=True).data
    annotations_data = AnnotationSerializer(annotations, many=True).data
    variations_data = StepVariationSerializer(variations, many=True).data
    sections_data = ProtocolSectionSerializer(sections, many=True).data
    session_data = SessionSerializer(sessions, many=True).data
    folders_data = AnnotationFolderSerializer(folders, many=True).data
    reagents_data = ReagentSerializer(reagents, many=True).data
    protocol_reagents_data = ProtocolReagentSerializer(protocol_reagents, many=True).data
    step_reagents_data = StepReagentSerializer(step_reagents, many=True).data
    tags_data = TagSerializer(tag, many=True).data
    protocol_tags_data = ProtocolTagSerializer(protocol_tags, many=True).data
    step_tags_data = StepTagSerializer(step_tags, many=True).data
    projects_data = ProjectSerializer(projects, many=True).data



    media_root = settings.MEDIA_ROOT
    user_folder = os.path.join(media_root, "temp", f"{user.username}")
    os.makedirs(user_folder, exist_ok=True)
    os.makedirs(os.path.join(user_folder, "projects"), exist_ok=True)
    os.makedirs(os.path.join(user_folder, "protocols"), exist_ok=True)
    os.makedirs(os.path.join(user_folder, "steps"), exist_ok=True)
    os.makedirs(os.path.join(user_folder, "annotations"), exist_ok=True)
    os.makedirs(os.path.join(user_folder, "variations"), exist_ok=True)
    os.makedirs(os.path.join(user_folder, "sections"), exist_ok=True)
    os.makedirs(os.path.join(user_folder, "sessions"), exist_ok=True)
    os.makedirs(os.path.join(user_folder, "folders"), exist_ok=True)
    os.makedirs(os.path.join(user_folder, "reagents"), exist_ok=True)
    os.makedirs(os.path.join(user_folder, "protocol_reagents"), exist_ok=True)
    os.makedirs(os.path.join(user_folder, "step_reagents"), exist_ok=True)
    os.makedirs(os.path.join(user_folder, "tags"), exist_ok=True)
    os.makedirs(os.path.join(user_folder, "protocol_tags"), exist_ok=True)
    os.makedirs(os.path.join(user_folder, "step_tags"), exist_ok=True)

    for project in projects_data:
        with open(os.path.join(user_folder, "projects", f"{project['id']}.json"), "wt") as f:
            json.dump(
                {
                    "id": project["id"],
                    "project_name": project["project_name"],
                    "project_description": project["project_description"]
                }, f)

    for protocol in protocols_data:
        with open(os.path.join(user_folder, "protocols", f"{protocol['id']}.json"), "wt") as f:
            json.dump(protocol, f)
    for step in protocols_steps_data:
        with open(os.path.join(user_folder, "steps", f"{step['id']}.json"), "wt") as f:
            print(step)
            json.dump(step, f)
    for annotation in annotations_data:
        with open(os.path.join(user_folder, "annotations", f"{annotation['id']}.json"), "wt") as f:
            json.dump(annotation, f)
    for variation in variations_data:
        with open(os.path.join(user_folder, "variations", f"{variation['id']}.json"), "wt") as f:
            json.dump(variation, f)
    for section in sections_data:
        with open(os.path.join(user_folder, "sections", f"{section['id']}.json"), "wt") as f:
            json.dump(section, f)
    for session in session_data:
        with open(os.path.join(user_folder, "sessions", f"{session['id']}.json"), "wt") as f:
            json.dump(session, f)
    for folder in folders_data:
        with open(os.path.join(user_folder, "folders", f"{folder['id']}.json"), "wt") as f:
            json.dump(folder, f)
    for reagent in reagents_data:
        with open(os.path.join(user_folder, "reagents", f"{reagent['id']}.json"), "wt") as f:
            json.dump(reagent, f)
    for protocol_ingredient in protocol_reagents_data:
        with open(os.path.join(user_folder, "protocol_reagents", f"{protocol_ingredient['id']}.json"), "wt") as f:
            json.dump(protocol_ingredient, f)
    for step_ingredient in step_reagents_data:
        with open(os.path.join(user_folder, "step_reagents", f"{step_ingredient['id']}.json"), "wt") as f:
            json.dump(step_ingredient, f)
    for tag in tags_data:
        with open(os.path.join(user_folder, "tags", f"{tag['id']}.json"), "wt") as f:
            json.dump(tag, f)
    for protocol_tag in protocol_tags_data:
        with open(os.path.join(user_folder, "protocol_tags", f"{protocol_tag['id']}.json"), "wt") as f:
            json.dump(protocol_tag, f)

    for step_tag in step_tags_data:
        with open(os.path.join(user_folder, "step_tags", f"{step_tag['id']}.json"), "wt") as f:
            json.dump(step_tag, f)

    os.makedirs(os.path.join(user_folder, "media", "annotations"), exist_ok=True)
    for i in annotations_data:
        if i["file"]:
            correct_path = i["file"].replace("/media/app/", "/app/")
            print(i)
            print(os.path.exists(correct_path))
            if not os.path.exists(correct_path):
                correct_path = "/app" + i["file"]
                print(os.path.exists(correct_path))
            new_path = os.path.join(user_folder, "media", "annotations", os.path.basename(correct_path))
            print(correct_path)
            print(new_path)
            shutil.copy(correct_path, new_path)
    if not filename:
        filename = str(uuid.uuid4())
        shutil.make_archive(os.path.join(media_root, "temp", f"{filename}"), 'gztar', user_folder)
    else:
        shutil.make_archive(filename, 'gztar', user_folder)
    shutil.rmtree(user_folder)
    return filename

@job('import-data', timeout='3h')
def import_data(user_id: int, tar_file: str, instance_id: str = None):
    import_user_data(user_id, tar_file, instance_id=instance_id)



def import_user_data(user_id: int, tar_file: str, instance_id: str = None):
    """
    A function that would import user's protocol, protocolstep, annotation, variation, and section data from individual jsons and archive into a tar.gz file
    :param user_id:
    :param tar_file:
    :return:
    """
    user = User.objects.get(id=user_id)
    media_root = settings.MEDIA_ROOT
    user_folder = os.path.join(media_root, "temp", f"{user.username}")
    annotation_folder = os.path.join(media_root, "annotations")
    os.makedirs(user_folder, exist_ok=True)
    shutil.unpack_archive(tar_file, user_folder, format="gztar")
    projects_folder = os.path.join(user_folder, "projects")
    protocols_folder = os.path.join(user_folder, "protocols")
    steps_folder = os.path.join(user_folder, "steps")
    annotations_folder = os.path.join(user_folder, "annotations")
    variations_folder = os.path.join(user_folder, "variations")
    sections_folder = os.path.join(user_folder, "sections")
    sessions_folder = os.path.join(user_folder, "sessions")
    annotationfolder_folder = os.path.join(user_folder, "folders")
    reagents_folder = os.path.join(user_folder, "reagents")
    protocol_reagents_folder = os.path.join(user_folder, "protocol_reagents")
    step_reagents_folder = os.path.join(user_folder, "step_reagents")
    tags_folder = os.path.join(user_folder, "tags")
    protocol_tags_folder = os.path.join(user_folder, "protocol_tags")
    step_tags_folder = os.path.join(user_folder, "step_tags")
    protocol_map = {}

    project_map = {}
    for project in os.listdir(projects_folder):
        with open(os.path.join(projects_folder, project), "rt") as f:
            data = json.load(f)
            project = Project()
            project.project_name = "[imported]" + data["project_name"] + str(datetime.datetime.now())
            project.project_description = data["project_description"]
            project.user = user
            project.save()
            project_map[data["id"]] = project

    for file in os.listdir(protocols_folder):
        with open(os.path.join(protocols_folder, file), "rt") as f:
            data = json.load(f)
            data["user"] = user_id
            if ProtocolModel.objects.filter(protocol_title=data["protocol_title"]).exists():
                date = datetime.datetime.now()
                data["protocol_title"] = "[imported] " + data["protocol_title"] + " " + str(date)

            protocol = ProtocolModel()
            protocol.protocol_created_on = data["protocol_created_on"]
            protocol.protocol_title = data["protocol_title"]
            protocol.protocol_description = data["protocol_description"]
            protocol.user = user
            protocol.save()
            protocol_map[data["id"]] = protocol
    tag_map = {}
    for file in os.listdir(tags_folder):
        with open(os.path.join(tags_folder, file), "rt") as f:
            data = json.load(f)
            instance = Tag.objects.get_or_create(tag=data["tag"])[0]
            tag_map[data["id"]] = instance
    protocol_tag_map = {}

    for file in os.listdir(protocol_tags_folder):
        with open(os.path.join(protocol_tags_folder, file), "rt") as f:
            data = json.load(f)
            data["protocol"] = protocol_map[data["protocol"]]
            data["tag"] = tag_map[data["tag"]["id"]]
            protocol_tag_data = {k: v for k, v in data.items() if k != "id"}
            instance = ProtocolTag.objects.create(**protocol_tag_data)
            protocol_tag_map[data["id"]] = instance

    section_map = {}
    for file in os.listdir(sections_folder):
        with open(os.path.join(sections_folder, file), "rt") as f:
            data = json.load(f)
            data["protocol"] = protocol_map[data["protocol"]].id
            serializer = ProtocolSectionSerializer(data=data)
            if serializer.is_valid():
                section_data = {k: v for k, v in serializer.validated_data.items() if k != "id" and k != "reagents" and k != "tags"}
                instance = ProtocolSection.objects.create(**section_data)
                instance.remote_id = data["id"]
                section_map[data["id"]] = instance
                instance.save()
    step_map = {}
    for file in os.listdir(steps_folder):
        with open(os.path.join(steps_folder, file), "rt") as f:
            data = json.load(f)
            data["protocol"] = protocol_map[data["protocol"]]
            data["step_section"] = section_map[data["step_section"]]
            step_data = {k: v for k, v in data.items() if k != "id" and k != "previous_step" and k != "next_step" and k != "annotations" and k != "variations" and k != "reagents" and k != "tags"}
            instance = ProtocolStep.objects.create(**step_data)
            step_map[data["id"]] = instance
            if data["previous_step"]:
                if data["previous_step"] in step_map:
                    step_map[data["previous_step"]].next_step.add(instance)
    step_tag_map = {}
    for file in os.listdir(step_tags_folder):
        with open(os.path.join(step_tags_folder, file), "rt") as f:
            data = json.load(f)
            data["step"] = step_map[data["step"]]
            data["tag"] = tag_map[data["tag"]["id"]]
            step_tag_data = {k: v for k, v in data.items() if k != "id"}
            instance = StepTag.objects.create(**step_tag_data)
            step_tag_map[data["id"]] = instance

    reagent_map = {}
    for file in os.listdir(reagents_folder):
        with open(os.path.join(reagents_folder, file), "rt") as f:
            data = json.load(f)
            serializer = ReagentSerializer(data=data)
            if serializer.is_valid():
                reagent_data = {k: v for k, v in serializer.validated_data.items() if k != "id"}
                instance = Reagent.objects.get_or_create(name=reagent_data["name"], unit=reagent_data["unit"])[0]
                reagent_map[data["id"]] = instance

    protocol_reagent_map = {}
    for file in os.listdir(protocol_reagents_folder):
        with open(os.path.join(protocol_reagents_folder, file), "rt") as f:
            data = json.load(f)
            data["protocol"] = protocol_map[data["protocol"]]
            data["reagent"] = reagent_map[data["reagent"]["id"]]
            protocol_reagent_data = {k: v for k, v in data.items() if k != "id"}

            instance = ProtocolReagent.objects.create(**protocol_reagent_data)
            protocol_reagent_map[data["id"]] = instance

    step_reagent_map = {}
    for file in os.listdir(step_reagents_folder):
        with open(os.path.join(step_reagents_folder, file), "rt") as f:
            data = json.load(f)
            data["step"] = step_map[data["step"]]
            data["reagent"] = reagent_map[data["reagent"]["id"]]
            step_reagent_data = {k: v for k, v in data.items() if k != "id"}
            instance = StepReagent.objects.create(**step_reagent_data)
            step_reagent_map[data["id"]] = instance
            description = data["step"].step_description
            for i in [f"%{data['id']}.name%", f"%{data['id']}.quantity%", f"%{data['id']}.unit%", f"%{data['id']}.scaled_quantity%"]:
                if i in description:
                    if i == f"%{data['id']}.name%":
                        description = description.replace(i, f"%{instance.id}.name%")
                    if i == f"%{data['id']}.quantity%":
                        description = description.replace(i, f"%{instance.id}.quantity%")
                    if i == f"%{data['id']}.unit%":
                        description = description.replace(i, f"%{instance.id}.unit%")
                    if i == f"%{data['id']}.scaled_quantity%":
                        description = description.replace(i, f"%{instance.id}.scaled_quantity%")
            data["step"].step_description = description
            data["step"].save()

    session_map = {}
    for file in os.listdir(sessions_folder):
        with open(os.path.join(sessions_folder, file), "rt") as f:
            data = json.load(f)
            data["user"] = user_id
            data["time_keeper"] = []
            data["protocols"] = [protocol_map[i].id for i in data["protocols"] if i in protocol_map]
            session = Session()
            session.user = user
            session.created_at = data["created_at"]
            session.updated_at = data["updated_at"]
            session.remote_id = data["id"]
            session.started_at = data["started_at"]
            session.ended_at = data["ended_at"]
            session.unique_id = uuid.uuid4().hex
            session.name = data["name"]
            session.processing = True
            session.save()
            for protocol in data["protocols"]:
                session.protocols.add(protocol)
            if "projects" in data:
                for project in data["projects"]:
                    session.projects.add(project_map[project])

            session_map[data["id"]] = session


    annotationfolder_map = {}
    annotationfolder_json_map = {}
    for file in os.listdir(annotationfolder_folder):
        with open(os.path.join(annotationfolder_folder, file), "rt") as f:
            data = json.load(f)
            annotationfolder_json_map[data["id"]] = data
            annotationfolder_map[data["id"]] = AnnotationFolder.objects.create(
                folder_name=data["folder_name"],
                session=session_map[data["session"]],
                parent_folder=None,
            )
    for i in annotationfolder_json_map:
        data = annotationfolder_json_map[i]
        if data["parent_folder"]:
            annotationfolder_map[i] = annotationfolder_map[data["parent_folder"]]
            annotationfolder_map[i].save()

    annotation_map = {}
    for file in os.listdir(annotations_folder):
        with open(os.path.join(annotations_folder, file), "rt") as f:

            data = json.load(f)
            folder = None
            if data["session"] not in session_map:
                continue
            if data["step"]:
                if data["step"] in step_map:
                    data["step"] = step_map[data["step"]]
                else:
                    continue
                data["remote_id"] = data["id"]

                if len(data["folder"]) > 0:
                    folder = annotationfolder_map[data["folder"][0]["id"]]
            instance = Annotation.objects.create(
                session=session_map[data["session"]],
                step=data["step"],
                annotation_type=data["annotation_type"],
                remote_id=data["id"],
                folder=folder
            )
            instance.annotation = data["annotation"]
            instance.transcribed = data["transcribed"]
            instance.transcription = data["transcription"]
            instance.language = data["language"]
            instance.translation = data["translation"]
            instance.user = user
            if data["file"]:
                file_path = os.path.join(user_folder, "media", "annotations", os.path.basename(data["file"]))
                #new_file_path = os.path.join(annotation_folder, str(user_id) + os.path.basename(data["file"]))
                #new_file_path = os.path.normpath(new_file_path)
                #shutil.copy(file_path, new_file_path)
                with open(file_path, "rb") as f:
                    instance.file.save(uuid.uuid4().hex + os.path.basename(data["file"]), f)
            instance.created_at = data["created_at"]
            instance.updated_at = data["updated_at"]
            instance.save()
            annotation_map[data["id"]] = instance

    for file in os.listdir(variations_folder):
        with open(os.path.join(variations_folder, file), "rt") as f:
            data = json.load(f)
            if data["step"] in step_map:
                data["step"] = step_map[data["step"]].id

            serializer = StepVariationSerializer(data=data)
            if serializer.is_valid():
                serializer.save()

    for i in session_map:
        session = session_map[i]
        session.processing = False
        session.save()

@job('export', timeout='3h')
def export_instrument_job_metadata(instrument_job_id: int, data_type: str, user_id: int, instance_id: str = None):
    instrument_job = InstrumentJob.objects.get(id=instrument_job_id)
    if data_type == "user_metadata":
        metadata = instrument_job.user_metadata.all()
    elif data_type == "staff_metadata":
        metadata = instrument_job.staff_metadata.all()
    else:
        metadata = list(instrument_job.user_metadata.all()) + list(instrument_job.staff_metadata.all())
    result, _ = sort_metadata(metadata, instrument_job.sample_number)
    # create tsv file from result
    filename = str(uuid.uuid4())
    tsv_filepath = os.path.join(settings.MEDIA_ROOT, "temp", f"{filename}.tsv")
    with open(tsv_filepath, "wt") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(result[0])
        for row in result[1:]:
            writer.writerow(row)
    signer = TimestampSigner()
    value = signer.sign(f"{filename}.tsv")
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"user_{user_id}_instrument_job",
        {
            "type": "download_message",
            "message": {
                "signed_value": value,
                "instance_id": instance_id
            },
        }
    )
    return value



def sort_metadata(metadata: list[MetadataColumn]|QuerySet, sample_number: int):
    id_metadata_column_map = {}
    headers = []
    default_columns_list = [{
        "name": "Source name", "type": "", "mandatory": True
    },
        {
            "name": "Organism", "type": "Characteristics", "mandatory": True
        }, {
            "name": "Organism part", "type": "Characteristics", "mandatory": True
        }, {
            "name": "Disease", "type": "Characteristics", "mandatory": True
        }, {
            "name": "Cell type", "type": "Characteristics", "mandatory": True
        }, {
            "name": "Biological replicate", "type": "Characteristics", "mandatory": True
        },
        {
          "name": 'Enrichment process', 'type': 'Characteristics', 'mandatory': True
        },
        {
            "name": "Material type", "type": "", "mandatory": True
        },
        {
            "name": "Assay name", "type": "", "mandatory": True
        }, {
            "name": "Technology type", "type": "", "mandatory": True
        },
        {
            "name": "Proteomics data acquisition method", "type": "Comment", "mandatory": True
        }

        , {"name": "Label", "type": "Comment", "mandatory": True},
        {"name": "Instrument", "type": "Comment", "mandatory": True},
        {"name": "Fraction identifier", "type": "Comment", "mandatory": True},
        {
            "name": "Technical replicate", "type": "Comment", "mandatory": True
        },
        {"name": "Cleavage agent details", "type": "Comment", "mandatory": True},
        {"name": "Modification parameters", "type": "Comment", "mandatory": True},
        {"name": "Dissociation method", "type": "Comment", "mandatory": True},
        {"name": "Precursor mass tolerance", "type": "Comment", "mandatory": True},
        {"name": "Fragment mass tolerance", "type": "Comment", "mandatory": True},
        {"name": "File uri", "type": "Comment", "mandatory": True},
        {"name": "Data file", "type": "Comment", "mandatory": True},
        {"name": "", "type": "Factor value", "mandatory": True},
    ]
    metadata_column_map = {}
    source_name_metadata = None
    assay_name_metadata = None
    material_type_metadata = None
    technology_type_metadata = None
    factor_value_columns = []
    metadata_cache = {}
    for m in metadata:
        if m.name not in metadata_cache:
            metadata_cache[m.name] = {}
        if m.value not in metadata_cache[m.name]:
            metadata_cache[m.name][m.value] = convert_metadata_column_value_to_sdrf(m.name.lower(), m.value)
        m.value = metadata_cache[m.name][m.value]
        if m.modifiers:
            m.modifiers = json.loads(m.modifiers)
            for n, mod in enumerate(m.modifiers):
                if mod["value"] not in metadata_cache[m.name]:
                    metadata_cache[m.name][mod["value"]] = convert_metadata_column_value_to_sdrf(m.name.lower(), mod["value"])
                m.modifiers[n]["value"] = metadata_cache[m.name][mod["value"]]
        else:
            m.modifiers = []
        if m.type != "Factor value":
            if m.name not in metadata_column_map:
                metadata_column_map[m.name] = []
            metadata_column_map[m.name].append(m)
        else:
            factor_value_columns.append(m)
    new_metadata = []

    non_default_columns = []
    default_column_map = {}
    for i in default_columns_list:
        default_column_map[i["name"]] = i
        if i["name"] in metadata_column_map and i["name"] != "Assay name" and i["name"] != "Source name" and i["name"] != "Material type" and i["name"] != "Technology type":
            new_metadata.extend(metadata_column_map[i["name"]])
        if i["name"] == "Assay name":
            if "Assay name" in metadata_column_map:
                assay_name_metadata = metadata_column_map[i["name"]][0]
        elif i["name"] == "Source name":
            if "Source name" in metadata_column_map:
                source_name_metadata = metadata_column_map["Source name"][0]
        elif i["name"] == "Material type":
            if "Material type" in metadata_column_map:
                material_type_metadata = metadata_column_map["Material type"][0]
        elif i["name"] == "Technology type":
            if "Technology type" in metadata_column_map:
                technology_type_metadata = metadata_column_map["Technology type"][0]

    for name in metadata_column_map:
        if name not in default_column_map and name != "Assay name" and name != "Source name" and name != "Material type" and name != "Technology type":
            non_default_columns.extend(metadata_column_map[name])

    # render an empty 2d array with number of row equal to job sample_number and number of columns equalt to number of metadata columns
    col_count = len(new_metadata) + len(non_default_columns)
    if source_name_metadata:
        col_count += 1
    if assay_name_metadata:
        col_count += 1
    if len(factor_value_columns) > 0:
        col_count += len(factor_value_columns)
    if material_type_metadata:
        col_count += 1
    if technology_type_metadata:
        col_count += 1
    data = [["" for i in range(col_count)] for j in range(sample_number)]
    # render in order, source name, characteristics, non type, comment and factor values
    # fill first column with source name
    last_characteristics = 0
    if source_name_metadata:
        headers.append("source name")
        if source_name_metadata.modifiers:
            modifiers = source_name_metadata.modifiers
            for m in modifiers:
                samples = parse_sample_indices_from_modifier_string(m["samples"])
                for s in samples:
                    data[s][0] = m["value"]
        for i in range(sample_number):
            if data[i][0] == "":
                data[i][0] = source_name_metadata.value
        id_metadata_column_map[source_name_metadata.id] = {"column": 0, "name": "source name", "type": "", "hidden": source_name_metadata.hidden}
        last_characteristics += 1
    # fill characteristics
    for i in range(0, len(new_metadata)):
        m = new_metadata[i]
        if m.type == "Characteristics":
            if m.name.lower() == 'tissue' or m.name.lower() == "organism part":
                headers.append("characteristics[organism part]")
            else:
                headers.append(f"characteristics[{m.name.lower()}]")
            if m.modifiers:
                modifiers = m.modifiers
                if modifiers:
                    for mod in modifiers:
                        samples = parse_sample_indices_from_modifier_string(mod["samples"])
                        for s in samples:
                            data[s][last_characteristics] = mod["value"]
            for j in range(sample_number):
                if data[j][last_characteristics] == "":
                    data[j][last_characteristics] = m.value
            id_metadata_column_map[m.id] = {"column": last_characteristics, "name": headers[-1], "type": "characteristics", "hidden": m.hidden}
            last_characteristics += 1
    # fill characteristics from non default columns
    for i in range(0, len(non_default_columns)):
        m = non_default_columns[i]
        if m.type == "Characteristics":
            headers.append(f"characteristics[{m.name.lower()}]")
            if m.modifiers:
                modifiers = m.modifiers
                if modifiers:
                    for mod in modifiers:
                        samples = parse_sample_indices_from_modifier_string(mod["samples"])
                        for s in samples:
                            data[s][last_characteristics] = mod["value"]
            for j in range(sample_number):
                if data[j][last_characteristics] == "":
                    data[j][last_characteristics] = m.value
            id_metadata_column_map[m.id] = {"column": last_characteristics, "name": headers[-1], "type": "characteristics", "hidden": m.hidden}
            last_characteristics += 1
    # fill material type column
    last_non_type = last_characteristics
    if material_type_metadata:
        headers.append("material type")
        if material_type_metadata.modifiers:
            modifiers = material_type_metadata.modifiers
            if modifiers:
                for m in modifiers:
                    samples = parse_sample_indices_from_modifier_string(m["samples"])
                    for s in samples:
                        data[s][last_non_type] = m["value"]
        for i in range(sample_number):
            if data[i][last_non_type] == "":
                data[i][last_non_type] = material_type_metadata.value
        id_metadata_column_map[material_type_metadata.id] = {"column": last_non_type, "name": "material type", "type": "", "hidden": material_type_metadata.hidden}
        last_non_type += 1
    # fill assay name column
    if assay_name_metadata:
        headers.append("assay name")
        if assay_name_metadata.modifiers:
            modifiers = assay_name_metadata.modifiers
            if modifiers:
                for m in modifiers:
                    samples = parse_sample_indices_from_modifier_string(m["samples"])
                    for s in samples:
                        data[s][last_non_type] = m["value"]
        for i in range(sample_number):
            if data[i][last_non_type] == "":
                data[i][last_non_type] = assay_name_metadata.value
        id_metadata_column_map[assay_name_metadata.id] = {"column": last_non_type, "name": "assay name", "type": "", "hidden": assay_name_metadata.hidden}
        last_non_type += 1
    # fill technology type column
    if technology_type_metadata:
        headers.append("technology type")
        if technology_type_metadata.modifiers:
            modifiers = technology_type_metadata.modifiers
            if modifiers:
                for m in modifiers:
                    samples = parse_sample_indices_from_modifier_string(m["samples"])
                    for s in samples:
                        data[s][last_non_type] = m["value"]
        for i in range(sample_number):
            if data[i][last_non_type] == "":
                data[i][last_non_type] = technology_type_metadata.value
        id_metadata_column_map[technology_type_metadata.id] = {"column": last_non_type, "name": "technology type", "type": "", "hidden": technology_type_metadata.hidden}
        last_non_type += 1
    # fill non type column
    for i in range(0, len(new_metadata)):
        m = new_metadata[i]
        if m.type == "":
            headers.append(m.name.lower())
            if m.modifiers:
                modifiers = m.modifiers
                if modifiers:
                    for mod in modifiers:
                        samples = parse_sample_indices_from_modifier_string(mod["samples"])
                        for s in samples:
                            data[s][last_non_type] = mod["value"]

            for j in range(sample_number):
                if data[j][last_non_type] == "":
                    data[j][last_non_type] = m.value
            id_metadata_column_map[m.id] = {"column": last_non_type, "name": headers[-1], "type": "", "hidden": m.hidden}
            last_non_type += 1
    # fill non type from non default columns
    for i in range(0, len(non_default_columns)):
        m = non_default_columns[i]
        if m.type == "":
            headers.append(m.name.lower())
            if m.modifiers:
                modifiers = m.modifiers
                if modifiers:
                    for mod in modifiers:
                        samples = parse_sample_indices_from_modifier_string(mod["samples"])
                        for s in samples:
                            data[s][last_non_type] = mod["value"]
            for j in range(sample_number):
                if data[j][last_non_type] == "":
                    data[j][last_non_type] = m.value
            id_metadata_column_map[m.id] = {"column": last_non_type, "name": headers[-1], "type": "", "hidden": m.hidden}
            last_non_type += 1
    # fill comment column
    last_comment = last_non_type
    for i in range(0, len(new_metadata)):
        m = new_metadata[i]
        if m.type == "Comment":
            headers.append(f"comment[{m.name.lower()}]")

            if m.modifiers:
                modifiers = m.modifiers
                if modifiers:
                    for mod in modifiers:
                        samples = parse_sample_indices_from_modifier_string(mod["samples"])
                        for s in samples:
                            data[s][last_comment] = mod["value"]
            for j in range(sample_number):
                if data[j][last_comment] == "":
                    data[j][last_comment] = m.value
            id_metadata_column_map[m.id] = {"column": last_comment, "name": headers[-1], "type": "comment", "hidden": m.hidden}
            last_comment += 1
    # fill comment from non default columns
    for i in range(0, len(non_default_columns)):
        m = non_default_columns[i]
        if m.type == "Comment":
            headers.append(f"comment[{m.name.lower()}]")

            if m.modifiers:
                modifiers = m.modifiers
                if modifiers:
                    for mod in modifiers:
                        samples = parse_sample_indices_from_modifier_string(mod["samples"])
                        for s in samples:
                            data[s][last_comment] = mod["value"]
            for j in range(sample_number):
                if data[j][last_comment] == "":
                    data[j][last_comment] = m.value
            id_metadata_column_map[m.id] = {"column": last_comment, "name": headers[-1], "type": "comment",  "hidden": m.hidden}
            last_comment += 1
    # write factor values

    for i in range(0, len(factor_value_columns)):
        m = factor_value_columns[i]
        if m.name == "Tissue" or m.name == "Organism part":
            m.name = "Organism part"
        headers.append(f"factor value[{m.name.lower()}]")
        if m.modifiers:
            modifiers = m.modifiers
            if modifiers:
                for mod in modifiers:
                    samples = parse_sample_indices_from_modifier_string(mod["samples"])
                    for s in samples:
                        data[s][last_comment] = mod["value"]
        for j in range(sample_number):
            if data[j][last_comment] == "":
                data[j][last_comment] = m.value
        id_metadata_column_map[m.id] = {"column": last_comment, "name": headers[-1], "type": "factor value", "hidden": m.hidden}
        last_comment += 1
    return [headers, *data], id_metadata_column_map

def parse_sample_indices_from_modifier_string(samples: str):
    """
    Sample indices is a string of comma separated integers and ranges of integers separated by hyphen. This will parse it into a sorted list of integers from lowest to highest
    :param samples:
    :return:
    """
    samples = samples.split(",")
    sample_indices = []
    for sample in samples:
        if "-" in sample:
            start, end = sample.split("-")
            sample_indices.extend(range(int(start)-1, int(end)))
        else:
            sample_indices.append(int(sample)-1)
    return sorted(sample_indices)

def convert_metadata_column_value_to_sdrf(column_name: str, value: str):
    """
    Convert metadata column value to SDRF format
    :param column_name:
    :param value:
    :return:
    """
    if value == "" and column_name in required_metadata_name:
        return "not applicable"

    if column_name == "subcellular location":
        if value:
            v = SubcellularLocation.objects.filter(location_identifier=value)
            if v.exists():
                if "AC=" in value:
                    return f"NT={value}"
                else:
                    return f"NT={value};AC={v.first().accession}"
            else:
                return f"NT={value}"
    if column_name == "organism":
        if value:
            v = Species.objects.filter(official_name=value)
            if v.exists():
                #return f"http://purl.obolibrary.org/obo/NCBITaxon_{v.first().taxon}"
                return f"{value}"
            else:
                return f"{value}"
    if column_name == "label":
        if value:
            v = MSUniqueVocabularies.objects.filter(name=value, term_type="sample attribute")
            if v.exists():
                return f"NT={value};AC={v.first().accession}"
            else:
                return f"NT={value}"
    if column_name == "instrument":
        if value:
            v = MSUniqueVocabularies.objects.filter(name=value, term_type="instrument")
            if v.exists():
                if "AC=" in value:
                    return f"NT={value}"
                else:
                    return f"NT={value};AC={v.first().accession}"
            else:
                return f"NT={value}"
    if column_name == "dissociation method":
        if value:
            v = MSUniqueVocabularies.objects.filter(name=value, term_type="dissociation method")
            if v.exists():
                if "AC=" in value:
                    return f"NT={value}"
                else:
                    return f"NT={value};AC={v.first().accession}"
            else:
                return f"{value}"
    if column_name == "cleavage agent details":
        if value:
            v = MSUniqueVocabularies.objects.filter(name=value, term_type="cleavage agent")
            if v.exists():
                if "AC=" in value:
                    return f"NT={value}"
                else:
                    return f"NT={value};AC={v.first().accession}"
            else:
                return f"{value}"
    if column_name == "enrichment process":
        if value:
            v = MSUniqueVocabularies.objects.filter(name=value, term_type="enrichment process")
            if v.exists():
                if "AC=" in value:
                    return f"NT={value}"
                else:
                    return f"AC={v.first().accession};NT={value}"
            else:
                return f"{value}"
    if column_name == "fractionation method":
        if value:
            v = MSUniqueVocabularies.objects.filter(name=value, term_type="fractionation method")
            if v.exists():
                if "AC=" in value:
                    return f"NT={value}"
                else:
                    return f"AC={v.first().accession};NT={value}"
            else:
                return value
    if column_name == "proteomics data acquisition method":
        if value:
            v = MSUniqueVocabularies.objects.filter(name=value, term_type="proteomics data acquisition method")
            if v.exists():
                if "AC=" in value:
                    return f"NT={value}"
                else:
                    return f"AC={v.first().accession};NT={value}"
            else:
                return value
    if column_name == "reduction reagent":
        if value:
            v = MSUniqueVocabularies.objects.filter(name=value, term_type="reduction reagent")
            if v.exists():
                if "AC=" in value:
                    return f"NT={value}"
                else:
                    return f"AC={v.first().accession};NT={value}"
            else:
                return value
    if column_name == "alkylation reagent":
        if value:
            v = MSUniqueVocabularies.objects.filter(name=value, term_type="alkylation reagent")
            if v.exists():
                if "AC=" in value:
                    return f"NT={value}"
                else:
                    return f"AC={v.first().accession};NT={value}"
            else:
                return value
    if column_name == "modification parameters":
        if value:
            v = Unimod.objects.filter(name=value.split(";")[0])
            if v.exists():
                if "AC=" in value or "ac=" in value:
                    return f"NT={value}"
                else:
                    return f"AC={v.first().accession};NT={value}"
            else:
                return value
    if column_name == "ms2 analyzer type":
        if value:
            v = MSUniqueVocabularies.objects.filter(name=value, term_type="mass analyzer type")
            if v.exists():
                if "AC=" in value:
                    return f"NT={value}"
                else:
                    return f"AC={v.first().accession};NT={value}"
            else:
                return value
    return value

def read_sdrf_file(file: str):
    """
    Import SDRF file
    :param file_path:
    :return:
    """

    with open(file, "rt") as f:
        reader = csv.reader(f, delimiter="\t")
        headers = next(reader)
        data = []
        for row in reader:
            data.append(row)
    return headers, data

def convert_sdrf_to_metadata(name: str, value: str):
    data = value.split(";")
    if name == "tissue" or name == "organism part":
        for i in data:
            if "NT=" in i:
                metadata_nt = i.split("=")[1]
                v = Tissue.objects.filter(identifier=metadata_nt)
                if v.exists():
                    return v.first().identifier

        return value
    if name == "subcellular location":
        for i in data:
            if "NT=" in i.upper():
                metadata_nt = i.split("=")[1]
                v = SubcellularLocation.objects.filter(location_identifier=metadata_nt)
                if v.exists():
                    return v.first().location_identifier
            if "AC=" in i.upper():
                metadata_ac = i.split("=")[1]
                v = SubcellularLocation.objects.filter(accession=metadata_ac)
                if v.exists():
                    return v.first().location_identifier
        return value
    if name == "organism":
        for i in data:
            if "http" in i:
                metadata_tx = i.split("_")[1]
                v = Species.objects.filter(taxon=metadata_tx)
                if v.exists():
                    return v.first().official_name
            else:
                return value
    if name == "label":
        for i in data:
            if "NT=" in i:
                metadata_nt = i.split("=")[1]
                v = MSUniqueVocabularies.objects.filter(name=metadata_nt, term_type="sample attribute")
                if v.exists():
                    return v.first().name
            if "AC=" in i:
                metadata_ac = i.split("=")[1]
                v = MSUniqueVocabularies.objects.filter(accession=metadata_ac, term_type="sample attribute")
                if v.exists():
                    return v.first().name
        return value
    if name == "instrument":
        for i in data:
            if "NT=" in i:
                metadata_nt = i.split("=")[1]
                v = MSUniqueVocabularies.objects.filter(name=metadata_nt, term_type="instrument")
                if v.exists():
                    return v.first().name
            if "AC=" in i:
                metadata_ac = i.split("=")[1]
                v = MSUniqueVocabularies.objects.filter(accession=metadata_ac, term_type="instrument")
                if v.exists():
                    return v.first().name
        return value
    if name == "dissociation method":
        for i in data:
            if "NT=" in i:
                metadata_nt = i.split("=")[1]
                v = MSUniqueVocabularies.objects.filter(name=metadata_nt, term_type="dissociation method")
                if v.exists():
                    return v.first().name
            if "AC=" in i:
                metadata_ac = i.split("=")[1]
                v = MSUniqueVocabularies.objects.filter(accession=metadata_ac, term_type="dissociation method")
                if v.exists():
                    return v.first().name
        return value
    if name == "cleavage agent details":
        for i in data:
            if "NT=" in i:
                metadata_nt = i.split("=")[1]
                v = MSUniqueVocabularies.objects.filter(name=metadata_nt, term_type="cleavage agent")
                if v.exists():
                    return v.first().name
            if "AC=" in i:
                metadata_ac = i.split("=")[1]
                v = MSUniqueVocabularies.objects.filter(accession=metadata_ac, term_type="cleavage agent")
                if v.exists():
                    return v.first().name
        return value
    if name == "enrichment process":
        for i in data:
            if "NT=" in i:
                metadata_nt = i.split("=")[1]
                v = MSUniqueVocabularies.objects.filter(name=metadata_nt, term_type="enrichment process")
                if v.exists():
                    return v.first().name
            if "AC=" in i:
                metadata_ac = i.split("=")[1]
                v = MSUniqueVocabularies.objects.filter(accession=metadata_ac, term_type="enrichment process")
                if v.exists():
                    return v.first().name
        return value
    if name == "fractionation method":
        for i in data:
            if "NT=" in i:
                metadata_nt = i.split("=")[1]
                v = MSUniqueVocabularies.objects.filter(name=metadata_nt, term_type="fractionation method")
                if v.exists():
                    return v.first().name
            if "AC=" in i:
                metadata_ac = i.split("=")[1]
                v = MSUniqueVocabularies.objects.filter(accession=metadata_ac, term_type="fractionation method")
                if v.exists():
                    return v.first().name
        return value
    if name == "proteomics data acquisition method":
        for i in data:
            if "NT=" in i:
                metadata_nt = i.split("=")[1]
                v = MSUniqueVocabularies.objects.filter(name=metadata_nt, term_type="proteomics data acquisition method")
                if v.exists():
                    return v.first().name
            if "AC=" in i:
                metadata_ac = i.split("=")[1]
                v = MSUniqueVocabularies.objects.filter(accession=metadata_ac, term_type="proteomics data acquisition method")
                if v.exists():
                    return v.first().name
        return value
    if name == "reduction reagent":
        for i in data:
            if "NT=" in i:
                metadata_nt = i.split("=")[1]
                v = MSUniqueVocabularies.objects.filter(name=metadata_nt, term_type="reduction reagent")
                if v.exists():
                    return v.first().name
            if "AC=" in i:
                metadata_ac = i.split("=")[1]
                v = MSUniqueVocabularies.objects.filter(accession=metadata_ac, term_type="reduction reagent")
                if v.exists():
                    return v.first().name
        return value

    if name == "alkylation reagent":
        for i in data:
            if "NT=" in i:
                metadata_nt = i.split("=")[1]
                v = MSUniqueVocabularies.objects.filter(name=metadata_nt, term_type="alkylation reagent")
                if v.exists():
                    return v.first().name
            if "AC=" in i:
                metadata_ac = i.split("=")[1]
                v = MSUniqueVocabularies.objects.filter(accession=metadata_ac, term_type="alkylation reagent")
                if v.exists():
                    return v.first().name
        return value
    if name == "modification parameters":
        for i in data:
            if "NT=" in i:
                metadata_nt = i.split("=")[1]
                v = Unimod.objects.filter(name=metadata_nt)
                if v.exists():
                    all_data = [metadata_nt]+[d for d in data if "NT=" not in d]
                    return ";".join(all_data)
            if "AC=" in i:
                metadata_ac = i.split("=")[1]
                v = Unimod.objects.filter(accession=metadata_ac)
                if v.exists():
                    all_data = [v.first().name] + [d for d in data if "NT=" not in d]
                    return ";".join(all_data)
        return value
    if name == "ms2 analyzer type":
        for i in data:
            if "NT=" in i:
                metadata_nt = i.split("=")[1]
                v = MSUniqueVocabularies.objects.filter(name=metadata_nt, term_type="mass analyzer type")
                if v.exists():
                    return v.first().name
            if "AC=" in i:
                metadata_ac = i.split("=")[1]
                v = MSUniqueVocabularies.objects.filter(accession=metadata_ac, term_type="mass analyzer type")
                if v.exists():
                    return v.first().name
        return value
    return value

@job('import-data', timeout='3h')
def import_sdrf_file(annotation_id: int, user_id: int, instrument_job_id: int, instance_id: str = None, data_type: str = "user_metadata"):
    """
    Import SDRF file
    :param completed_chunk_file_id
    :param user_id:
    :param instrument_job_id:
    :param instance_id:
    :return:
    """
    annotation = Annotation.objects.get(id=annotation_id)
    headers, data = read_sdrf_file(annotation.file.path)
    instrument_job = InstrumentJob.objects.get(id=instrument_job_id)
    metadata_columns = []
    user_metadata_field_map = {}
    for i in user_metadata:
        if i['type'] not in user_metadata_field_map:
            user_metadata_field_map[i['type']] = {}
        user_metadata_field_map[i['type']][i['name']] = i
    staff_metadata_field_map = {}
    for i in staff_metadata:
        if i['type'] not in staff_metadata_field_map:
            staff_metadata_field_map[i['type']] = {}
        staff_metadata_field_map[i['type']][i['name']] = i

    for header in headers:
        metadata_column = MetadataColumn()
        header = header.lower()
        #extract type from pattern <type>[<name>]
        if "[" in header:
            type = header.split("[")[0]
            name = header.split("[")[1].replace("]", "")
        else:
            type = ""
            name = header
        #if name == "organism part":
        #    name = "tissue"
        metadata_column.name = name.capitalize().replace("Ms1", "MS1").replace("Ms2", "MS2")
        metadata_column.type = type.capitalize()
        metadata_columns.append(metadata_column)
    if len(data) != instrument_job.sample_number:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"user_{user_id}_instrument_job",
            {
                "type": "instrument_job_message",
                "message": {
                    "instance_id": instance_id,
                    "status": "warning",
                    "message": "Number of samples in SDRF file does not match the number of samples in the job"
                },
            }
        )
        # extend the number of samples to match the number of samples in the job and fill with empty strings
        if len(data) < instrument_job.sample_number:
            data.extend(
                [
                    ["" for i in range(len(headers))]
                    for j in range(instrument_job.sample_number - len(data))
                ]
            )

        else:
            data = data[:instrument_job.sample_number]

    if data_type == "user_metadata":
        for m in instrument_job.user_metadata.all():
            m.delete()
        instrument_job.user_metadata.clear()
    elif data_type == "staff_metadata":
        for m in instrument_job.staff_metadata.all():
            m.delete()
        instrument_job.staff_metadata.clear()
    else:
        for m in instrument_job.user_metadata.all():
            m.delete()
        instrument_job.user_metadata.clear()
        for m in instrument_job.staff_metadata.all():
            m.delete()
        instrument_job.staff_metadata.clear()
    for i in range(len(metadata_columns)):
        metadata_value_map = {}
        for j in range(len(data)):
            name = metadata_columns[i].name.lower()
            if data[j][i] == "":
                continue
            if data[j][i] == "not applicable":
                metadata_columns[i].not_applicable = True
                continue
            value = convert_sdrf_to_metadata(name, data[j][i])
            if value not in metadata_value_map:
                metadata_value_map[value] = []
            metadata_value_map[value].append(j)
        # get value with the highest count
        max_count = 0
        max_value = None
        for value in metadata_value_map:
            if len(metadata_value_map[value]) > max_count:
                max_count = len(metadata_value_map[value])
                max_value = value
        if max_value:
            metadata_columns[i].value = max_value
            metadata_columns[i].save()
        # calculate modifiers from the rest of the values
        modifiers = []
        for value in metadata_value_map:
            if value != max_value:
                modifier = {"samples": [], "value": value}
                # sort from lowest to highest. add samples index. for continuous samples, add range
                samples = metadata_value_map[value]
                samples.sort()
                start = samples[0]
                end = samples[0]
                for i2 in range(1, len(samples)):
                    if samples[i2] == end + 1:
                        end = samples[i2]
                    else:
                        if start == end:
                            modifier["samples"].append(str(start+1))
                        else:
                            modifier["samples"].append(f"{start+1}-{end+1}")
                        start = samples[i2]
                        end = samples[i2]
                if start == end:
                    modifier["samples"].append(str(start+1))
                else:
                    modifier["samples"].append(f"{start+1}-{end+1}")
                if len(modifier["samples"]) == 1:
                    modifier["samples"] = modifier["samples"][0]
                else:
                    modifier["samples"] = ",".join(modifier["samples"])
                modifiers.append(modifier)
        if modifiers:
            metadata_columns[i].modifiers = json.dumps(modifiers)
        metadata_columns[i].save()
        if data_type == "user_metadata":
            instrument_job.user_metadata.add(metadata_columns[i])
        elif data_type == "staff_metadata":
            instrument_job.staff_metadata.add(metadata_columns[i])
        else:
            if metadata_columns[i].type in user_metadata_field_map:
                if metadata_columns[i].name in user_metadata_field_map[metadata_columns[i].type]:
                    instrument_job.user_metadata.add(metadata_columns[i])
                else:
                    instrument_job.staff_metadata.add(metadata_columns[i])
            else:
                instrument_job.staff_metadata.add(metadata_columns[i])

    channel_layer = get_channel_layer()
    #notify user through channels that it has completed
    async_to_sync(channel_layer.group_send)(
        f"user_{user_id}_instrument_job",
        {
            "type": "instrument_job_message",
            "message": {
                "instance_id": instance_id,
                "status": "completed",
                "message": "Metadata imported successfully"
            },
        }
    )

@job('import-data', timeout='3h')
def validate_sdrf_file(metadata_column_ids: list[int], sample_number: int, user_id: int, instance_id: str):
    """

    :param metadata_column_ids:
    :param user_id:
    :param instance_id:
    :return:
    """

    metadata_column = MetadataColumn.objects.filter(id__in=metadata_column_ids)
    result, _ = sort_metadata(metadata_column, sample_number)
    # check if there is NoneType in the result
    errors = sdrf_validate(result)
    channel_layer = get_channel_layer()
    if errors:
        async_to_sync(channel_layer.group_send)(
            f"user_{user_id}_instrument_job",
            {
                "type": "instrument_job_message",
                "message": {
                    "instance_id": instance_id,
                    "status": "error",
                    "message": "Validation failed",
                    "errors": [str(e) for e in errors]
                },
            }
        )
    else:
        async_to_sync(channel_layer.group_send)(
            f"user_{user_id}_instrument_job",
            {
                "type": "instrument_job_message",
                "message": {
                    "instance_id": instance_id,
                    "status": "completed",
                    "message": "Validation successful"
                },
            }
        )


def sdrf_validate(result):
    df = pd.DataFrame()
    try:
        df = SdrfDataFrame.parse(io.StringIO("\n".join(["\t".join(i) for i in result])))
    except TypeError:
        errors = ["Invalid data in the SDRF file"]
    except KeyError:
        errors = ["Missing required columns in the SDRF file"]
    if isinstance(df, SdrfDataFrame):
        try:
            errors = df.validate("default", True)
        except Exception as e:
            errors = [str(e)]
        errors = errors + df.validate("mass_spectrometry", True)
        errors = errors + df.validate_experimental_design()
    return errors


@job('export', timeout='3h')
def export_excel_template(user_id: int, instance_id: str, instrument_job_id: int, export_type: str = "user_metadata"):
    """
    Export excel template
    :param user_id:
    :param instance_id:
    :param instrument_job_id:
    :return:
    """
    instrument_job = InstrumentJob.objects.get(id=instrument_job_id)
    field_mask_map = {}
    if instrument_job.selected_template:
        if instrument_job.selected_template.field_mask_mapping:
            for i in json.loads(instrument_job.selected_template.field_mask_mapping):
                field_mask_map[i["name"]] = i["mask"]
    if export_type=="user_metadata":
        metadata = list(instrument_job.user_metadata.all())
    elif export_type=="staff_metadata":
        metadata = list(instrument_job.staff_metadata.all())
    else:
        metadata = list(instrument_job.user_metadata.all()) + list(instrument_job.staff_metadata.all())

    main_metadata = [m for m in metadata if not m.hidden]
    hidden_metadata = [m for m in metadata if m.hidden]
    result_main, id_map_main = sort_metadata(main_metadata, instrument_job.sample_number)
    result_hidden = []
    id_map_hidden = {}
    if hidden_metadata:
        result_hidden, id_map_hidden = sort_metadata(hidden_metadata, instrument_job.sample_number)

    # get favourites for each metadata column
    favourites = {}
    user_favourite = FavouriteMetadataOption.objects.filter(user_id=user_id, service_lab_group__isnull=True, lab_group__isnull=True)
    facility_recommended = FavouriteMetadataOption.objects.filter(service_lab_group=instrument_job.service_lab_group)
    global_recommendations = FavouriteMetadataOption.objects.filter(is_global=True)
    for r in list(user_favourite):
        if r.name.lower() not in favourites:
            favourites[r.name.lower()] = []
        favourites[r.name.lower()].append(f"{r.display_value}[*]")
    for r in list(facility_recommended):
        if r.name.lower() not in favourites:
            favourites[r.name.lower()] = []
        favourites[r.name.lower()].append(f"{r.display_value}[**]")
        if r.name.lower() == "tissue" or r.name.lower() == "organism part" or r.name.lower() in required_metadata_name:
            favourites[r.name.lower()].append("not applicable")
    for r in list(global_recommendations):
        if r.name.lower() not in favourites:
            favourites[r.name.lower()] = []
        favourites[r.name.lower()].append(f"{r.display_value}[***]")

    # based on column name from result, contruct an excel file with the appropriate rows beside the header row where the cell with the same name in favourite can have preset selection options dropdown related to that column
    wb = Workbook()
    main_ws = wb.active
    main_ws.title = "main"
    hidden_ws = wb.create_sheet(title="hidden")
    id_metadata_column_map_ws = wb.create_sheet(title="id_metadata_column_map")
    # fill in the id_metadata_column_map_ws with 3 columns: id, name, type
    id_metadata_column_map_ws.append(["id", "column", "name", "type", "hidden"])

    for k, v in id_map_main.items():
        id_metadata_column_map_ws.append([k, v["column"], v["name"], v["type"], v["hidden"]])
    for k, v in id_map_hidden.items():
        id_metadata_column_map_ws.append([k, v["column"], v["name"], v["type"], v["hidden"]])

    fill = PatternFill(start_color="FFFF99", end_color="FFFF99", fill_type="solid")
    thin_border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'),
                         bottom=Side(style='thin'))

    # Append headers and data to the main worksheet
    main_ws.append(result_main[0])
    main_work_area = f"A1:{get_column_letter(len(result_main[0]))}{instrument_job.sample_number + 1}"

    for row in result_main[1:]:
        main_ws.append(row)
    for row in main_ws[main_work_area]:
        for cell in row:
            cell.fill = fill
            cell.border = thin_border

    for col in main_ws.columns:
        max_length = 0
        column = col[0].column_letter  # Get the column name
        for cell in col:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(cell.value)
            except:
                pass
        adjusted_width = (max_length + 2)
        main_ws.column_dimensions[column].width = adjusted_width

    note_texts = [
        "Note: Cells that are empty will automatically be filled with 'not applicable' or 'no available' depending on the column when submitted.",
        "[*] User-specific favourite options.",
        "[**] Facility-recommended options.",
        "[***] Global recommendations."
    ]

    start_row = instrument_job.sample_number + 2
    for i, note_text in enumerate(note_texts):
        main_ws.merge_cells(start_row=start_row + i, start_column=1, end_row=start_row + i,
                            end_column=len(result_main[0]))
        note_cell = main_ws.cell(row=start_row + i, column=1)
        note_cell.value = note_text
        note_cell.alignment = Alignment(horizontal='left', vertical='center')

    # Append headers and data to the hidden worksheet
    if len(result_hidden) > 0:
        hidden_work_area = f"A1:{get_column_letter(len(result_hidden[0]))}{instrument_job.sample_number + 1}"
        if len(result_hidden) > 1:
            hidden_ws.append(result_hidden[0])
            for row in result_hidden[1:]:
                hidden_ws.append(row)

            for row in hidden_ws[hidden_work_area]:
                for cell in row:
                    cell.fill = fill
                    cell.border = thin_border

            for col in hidden_ws.columns:
                max_length = 0
                column = col[0].column_letter  # Get the column name
                for cell in col:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(cell.value)
                    except:
                        pass
                adjusted_width = (max_length + 2)
                hidden_ws.column_dimensions[column].width = adjusted_width

    for i, header in enumerate(result_main[0]):
        name_splitted = result_main[0][i].split("[")
        required_column = False
        if len(name_splitted) > 1:
            name = name_splitted[1].replace("]", "")
        else:
            name = name_splitted[0]
        if name in required_metadata_name:
            required_column = True
        name_capitalized = name.capitalize().replace("Ms1", "MS1").replace("Ms2", "MS2")
        if name_capitalized in field_mask_map:
            name = field_mask_map[name_capitalized]
            if len(name_splitted) > 1:
                main_ws.cell(row=1, column=i + 1).value = result_main[0][i].replace(name_splitted[1].rstrip("]"), name.lower())
            else:
                main_ws.cell(row=1, column=i + 1).value =  name.lower()
        option_list = []
        if required_column:
            option_list.append(f"not applicable")
        else:
            option_list.append("not available")

        if name.lower() in favourites:
            option_list = option_list + favourites[name.lower()]
        dv = DataValidation(
            type="list",
            formula1=f'"{",".join(option_list)}"',
            showDropDown=False
        )
        col_letter = get_column_letter(i + 1)
        main_ws.add_data_validation(dv)
        dv.add(f"{col_letter}2:{col_letter}{instrument_job.sample_number + 1}")
    if len(result_hidden) > 1:
        for i, header in enumerate(result_hidden[0]):
            name_splitted = result_hidden[0][i].split("[")
            if len(name_splitted) > 1:
                name = name_splitted[1].replace("]", "")
            else:
                name = name_splitted[0]
            required_column = False
            if name in required_metadata_name:
                required_column = True
            name_capitalized = name.capitalize().replace("Ms1", "MS1").replace("Ms2", "MS2")
            if name_capitalized in field_mask_map:
                name = field_mask_map[name_capitalized]
                if len(name_splitted) > 1:
                    hidden_ws.cell(row=1, column=i + 1).value = result_hidden[0][i].replace(name_splitted[1].rstrip("]"), name.lower())
                else:
                    hidden_ws.cell(row=1, column=i + 1).value = name.lower()

            option_list = []
            if required_column:
                option_list.append(f"not applicable")
            else:
                option_list.append("not available")
            if name.lower() in favourites:
                option_list = option_list + favourites[name.lower()]
            dv = DataValidation(
                type="list",
                formula1=f'"{",".join(option_list)}"',
                showDropDown=False
            )
            col_letter = get_column_letter(i + 1)
            hidden_ws.add_data_validation(dv)
            dv.add(f"{col_letter}2:{col_letter}{instrument_job.sample_number + 1}")

    # save the file
    filename = str(uuid.uuid4())
    xlsx_filepath = os.path.join(settings.MEDIA_ROOT, "temp", f"{filename}.xlsx")

    wb.save(xlsx_filepath)
    signer = TimestampSigner()
    value = signer.sign(f"{filename}.xlsx")

    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"user_{user_id}_instrument_job",
        {
            "type": "download_message",
            "message": {
                "signed_value": value,
                "instance_id": instance_id
            },
        }
    )

@job('import-data', timeout='3h')
def import_excel(annotation_id: int, user_id: int, instrument_job_id: int, instance_id: str = None, data_type: str = "user_metadata"):
    """
    Import excel file
    :param file:
    :param user_id:
    :param instrument_job_id:
    :param instance_id:
    :return:
    """
    annotation = Annotation.objects.get(id=annotation_id)
    wb = load_workbook(annotation.file.path)
    main_ws = wb["main"]
    main_headers = [cell.value for cell in main_ws[1]]
    main_data = [list(row) for row in main_ws.iter_rows(min_row=2, values_only=True)]
    hidden_ws = None
    hidden_headers = []
    hidden_data = []
    id_metadata_column_map_ws = wb["id_metadata_column_map"]
    id_metadata_column_map_list = [list(row) for row in id_metadata_column_map_ws.iter_rows(min_row=2, values_only=True)]
    id_metadata_column_map = {}
    for row in id_metadata_column_map_list:
        id_metadata_column_map[int(row[0])] = {"column": row[1], "name": row[2], "type": row[3], "hidden": row[4]}
    if "hidden" in wb.sheetnames:
        hidden_ws = wb["hidden"]
        # check if there is any data in the hidden sheet
        if hidden_ws.max_row == 1:
            hidden_ws = None
        else:
            hidden_headers = [cell.value for cell in hidden_ws[1]]
            hidden_data = [list(row) for row in hidden_ws.iter_rows(min_row=2, values_only=True)]

    instrument_job = InstrumentJob.objects.get(id=instrument_job_id)
    metadata_columns = []

    user_metadata_field_map = {}
    staff_metadata_field_map = {}
    read_only_metadata_map = {}
    field_mask_map = {}
    if instrument_job.selected_template:
        field_mask_mapping = instrument_job.selected_template.field_mask_mapping
        if field_mask_mapping:
            for i in json.loads(field_mask_mapping):
                field_mask_map[i["mask"]] = i["name"]
        user_columns = list(instrument_job.user_metadata.all())
        staff_columns = list(instrument_job.staff_metadata.all())
        for i in user_columns:
            if i.type not in user_metadata_field_map:
                user_metadata_field_map[i.type] = {}
            if i.name not in user_metadata_field_map[i.type]:
                user_metadata_field_map[i.type][i.name] = []
            um = {"id": i.id, "type": i.type, "name": i.name, "hidden": i.hidden, "value": i.value, "modifiers": i.modifiers}
            user_metadata_field_map[i.type][i.name].append(um)


        for i in staff_columns:
            if i.type not in staff_metadata_field_map:
                staff_metadata_field_map[i.type] = {}
            if i.name not in staff_metadata_field_map[i.type]:
                staff_metadata_field_map[i.type][i.name] = []

            sm = {"id": i.id, "type": i.type, "name": i.name, "hidden": i.hidden, "value": i.value, "modifiers": i.modifiers}
            staff_metadata_field_map[i.type][i.name].append(sm)
    else:
        for i in user_metadata:
            if i['type'] not in user_metadata_field_map:
                user_metadata_field_map[i['type']] = {}
            if i['name'] not in user_metadata_field_map[i['type']]:
                user_metadata_field_map[i['type']][i['name']] = []
            user_metadata_field_map[i['type']][i['name']].append(i)
        for i in staff_metadata:
            if i['type'] not in staff_metadata_field_map:
                staff_metadata_field_map[i['type']] = {}
            if i['name'] not in staff_metadata_field_map[i['type']]:
                staff_metadata_field_map[i['type']][i['name']] = []
            staff_metadata_field_map[i['type']][i['name']].push(i)

    for n, header in enumerate(main_headers):
        id_from_map = 0
        for row in id_metadata_column_map_list:
            row_data = id_metadata_column_map[int(row[0])]
            if row_data["column"] == n and not row_data["hidden"]:
                id_from_map = int(row[0])
                break
        metadata_column = MetadataColumn.objects.filter(id=id_from_map)
        if metadata_column.exists():
            metadata_column = metadata_column.first()
        else:
            metadata_column = MetadataColumn()
            header = header.lower()
            if "[" in header:
                type = header.split("[")[0]
                name = header.split("[")[1].replace("]", "")
            else:
                type = ""
                name = header
            name_capitalized = name.capitalize().replace("Ms1", "MS1").replace("Ms2", "MS2")
            if name_capitalized in field_mask_map:
                name = field_mask_map[name_capitalized]
            metadata_column.name = name
            metadata_column.type = type.capitalize()
            metadata_column.hidden = False
            metadata_column.readonly = False
        metadata_columns.append(metadata_column)

    for n, header in enumerate(hidden_headers):
        id_from_map = 0
        for row in id_metadata_column_map_list:
            row_data = id_metadata_column_map[int(row[0])]
            if row_data["column"] == n and row_data["hidden"]:
                id_from_map = int(row[0])
                break

        if id_from_map != 0:
            metadata_column = MetadataColumn.objects.get(id=id_from_map)
        else:
            metadata_column = MetadataColumn()
            header = header.lower()
            if "[" in header:
                type = header.split("[")[0]
                name = header.split("[")[1].replace("]", "")
            else:
                type = ""
                name = header
            name_capitalized = name.capitalize().replace("Ms1", "MS1").replace("Ms2", "MS2")
            if name_capitalized in field_mask_map:
                name = field_mask_map[name_capitalized]
            metadata_column.name = name
            metadata_column.type = type.capitalize()
            metadata_column.hidden = True
        metadata_columns.append(metadata_column)
    if len(hidden_data) > 0:
        headers = main_headers + hidden_headers
        data = [main_row + hidden_row for main_row, hidden_row in zip(main_data, hidden_data)]
    else:
        headers = main_headers
        data = main_data
    if len(data) != instrument_job.sample_number:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"user_{user_id}_instrument_job",
            {
                "type": "instrument_job_message",
                "message": {
                    "instance_id": instance_id,
                    "status": "warning",
                    "message": "Number of samples in excel file does not match the number of samples in the job"
                },
            }
        )
        # extend the number of samples to match the number of samples in the job and
        # fill with empty strings

        if len(data) < instrument_job.sample_number:
            data.extend(
                [
                    ["" for i in range(len(headers))]
                    for j in range(instrument_job.sample_number - len(data))
                ]
            )

        else:
            data = data[:instrument_job.sample_number]

    if data_type == "user_metadata":
        instrument_job.user_metadata.clear()
    elif data_type == "staff_metadata":
        instrument_job.staff_metadata.clear()
    else:
        instrument_job.user_metadata.clear()
        instrument_job.staff_metadata.clear()

    for i in range(len(metadata_columns)):
        if metadata_columns[i].readonly:
            # check if the metadata column exists in the read_only_metadata_map then remove the reference from the map
            if data_type == "user_metadata":
                check_and_remove_metadata_from_map(i, metadata_columns, user_metadata_field_map)

            elif data_type == "staff_metadata":
                check_and_remove_metadata_from_map(i, metadata_columns, staff_metadata_field_map)
            else:
                check_and_remove_metadata_from_map(i, metadata_columns, user_metadata_field_map)
                check_and_remove_metadata_from_map(i, metadata_columns, staff_metadata_field_map)
            continue
        metadata_value_map = {}
        for j in range(len(data)):
            name = metadata_columns[i].name.lower()
            if data[j][i] is None:
                data[j][i] = ""
            if data[j][i] == "":
                if name == "tissue" or name in required_metadata_name:
                    data[j][i] = "not applicable"
                else:
                    data[j][i] = "not available"
            if data[j][i] == "not applicable" or data[j][i] == "not available":
                value = data[j][i]
            elif data[j][i].endswith("[*]"):
                value = data[j][i].replace("[*]", "")
                value_query = FavouriteMetadataOption.objects.filter(user_id=user_id, name=name, display_value=value, service_lab_group__isnull=True, lab_group__isnull=True)
                if value_query.exists():
                    value = value_query.first().value
                value = convert_sdrf_to_metadata(name, value)
            elif data[j][i].endswith("[**]"):
                value = data[j][i].replace("[**]", "")
                value_query = FavouriteMetadataOption.objects.filter(name=name, service_lab_group=instrument_job.service_lab_group, display_value=value)
                if value_query.exists():
                    value = value_query.first().value
                value = convert_sdrf_to_metadata(name, value)
            elif data[j][i].endswith("[***]"):
                value = data[j][i].replace("[***]", "")
                value_query = FavouriteMetadataOption.objects.filter(name=name, is_global=True, display_value=value)
                if value_query.exists():
                    value = value_query.first().value
                value = convert_sdrf_to_metadata(name, value)
            else:
                value = convert_sdrf_to_metadata(name, data[j][i])
            if value not in metadata_value_map:
                metadata_value_map[value] = []
            metadata_value_map[value].append(j)
        # get value with the highest count
        max_count = 0
        max_value = None
        for value in metadata_value_map:
            if len(metadata_value_map[value]) > max_count:
                max_count = len(metadata_value_map[value])
                max_value = value
        if max_value:
            metadata_columns[i].value = max_value
            metadata_columns[i].save()
        # calculate modifiers from the rest of the values
        modifiers = []
        for value in metadata_value_map:
            if value != max_value:
                modifier = {"samples": [], "value": value}
                # sort from lowest to highest. add samples index. for continuous samples, add range
                samples = metadata_value_map[value]
                samples.sort()
                start = samples[0]
                end = samples[0]
                for i2 in range(1, len(samples)):
                    if samples[i2] == end + 1:
                        end = samples[i2]
                    else:
                        if start == end:
                            modifier["samples"].append(str(start + 1))
                        else:
                            modifier["samples"].append(f"{start + 1}-{end + 1}")
                        start = samples[i2]
                        end = samples[i2]
                if start == end:
                    modifier["samples"].append(str(start + 1))
                else:
                    modifier["samples"].append(f"{start + 1}-{end + 1}")
                if len(modifier["samples"]) == 1:
                    modifier["samples"] = modifier["samples"][0]
                else:
                    modifier["samples"] = ",".join(modifier["samples"])
                modifiers.append(modifier)
        if modifiers:
            metadata_columns[i].modifiers = json.dumps(modifiers)

        if data_type == "user_metadata":
            if metadata_columns[i].id:
                metadata_columns[i].save()
                check_and_remove_metadata_from_map(i, metadata_columns, user_metadata_field_map)
            else:
                # check if the metadata column exists in the user_metadata_field_map then remove the reference from the map
                check_metadata_column_create_then_remove_from_map(i, instrument_job, metadata_columns,
                                                                  user_metadata_field_map, "user_metadata")
        elif data_type == "staff_metadata":
            if metadata_columns[i].id:
                metadata_columns[i].save()
                check_and_remove_metadata_from_map(i, metadata_columns, staff_metadata_field_map)
            else:
                # check if the metadata column exists in the staff_metadata_field_map then remove the reference from the map
                check_metadata_column_create_then_remove_from_map(i, instrument_job, metadata_columns,
                                                                  staff_metadata_field_map, "staff_metadata")
        else:
            if metadata_columns[i].type in staff_metadata_field_map:
                if metadata_columns[i].name in staff_metadata_field_map[metadata_columns[i].type]:
                    first_column = staff_metadata_field_map[metadata_columns[i].type][metadata_columns[i].name][0]
                    if metadata_columns[i].id:
                        metadata_columns[i].save()
                        instrument_job.staff_metadata.add(metadata_columns[i])
                    else:
                        first_column["value"] = metadata_columns[i].value
                        first_column["modifiers"] = metadata_columns[i].modifiers
                        first_column["hidden"] = metadata_columns[i].hidden
                        first_column["readonly"] = metadata_columns[i].readonly
                        m = MetadataColumn.objects.create(**first_column)
                        instrument_job.staff_metadata.add(m)
                    staff_metadata_field_map[metadata_columns[i].type][metadata_columns[i].name].pop(0)
                    if len(staff_metadata_field_map[metadata_columns[i].type][metadata_columns[i].name]) == 0:
                        del staff_metadata_field_map[metadata_columns[i].type][metadata_columns[i].name]
                else:
                    check_metadata_column_create_then_remove_from_map(i, instrument_job, metadata_columns,
                                                                      user_metadata_field_map, "user_metadata")
            else:
                check_metadata_column_create_then_remove_from_map(i, instrument_job, metadata_columns,
                                                                  user_metadata_field_map, "user_metadata")
    # check if there are any metadata columns left in the user_metadata_field_map and staff_metadata_field_map
    for d_type in user_metadata_field_map:
        for name in user_metadata_field_map[d_type]:
            for i in user_metadata_field_map[d_type][name]:
                i.delete()
    for d_type in staff_metadata_field_map:
        for name in staff_metadata_field_map[d_type]:
            for i in staff_metadata_field_map[d_type][name]:
                i.delete()

    channel_layer = get_channel_layer()
    # notify user through channels that it has completed
    async_to_sync(channel_layer.group_send)(
        f"user_{user_id}_instrument_job",
        {
            "type": "instrument_job_message",
            "message": {
                "instance_id": instance_id,
                "status": "completed",
                "message": "Metadata imported successfully"
            },
        }
    )


def check_metadata_column_create_then_remove_from_map(i, instrument_job, metadata_columns, metadata_field_map, field_type):
    if metadata_columns[i].type in metadata_field_map:
        if metadata_columns[i].name in metadata_field_map[metadata_columns[i].type]:
            first_column = metadata_field_map[metadata_columns[i].type][metadata_columns[i].name][0]
            if metadata_columns[i].id:
                metadata_columns[i].save()
                if field_type == "user_metadata":
                    instrument_job.user_metadata.add(metadata_columns[i])
                else:
                    instrument_job.staff_metadata.add(metadata_columns[i])
            else:
                first_column["value"] = metadata_columns[i].value
                first_column["modifiers"] = metadata_columns[i].modifiers
                first_column["hidden"] = metadata_columns[i].hidden
                first_column["readonly"] = metadata_columns[i].readonly
                m = MetadataColumn.objects.create(**first_column)
                if field_type == "user_metadata":
                    instrument_job.user_metadata.add(m)
                else:
                    instrument_job.staff_metadata.add(m)
            metadata_field_map[metadata_columns[i].type][metadata_columns[i].name].pop(0)
            if len(metadata_field_map[metadata_columns[i].type][metadata_columns[i].name]):
                del metadata_field_map[metadata_columns[i].type][metadata_columns[i].name]
        else:
            metadata_columns[i].save()
            if field_type == "user_metadata":
                instrument_job.user_metadata.add(metadata_columns[i])
            else:
                instrument_job.staff_metadata.add(metadata_columns[i])
    else:
        metadata_columns[i].save()
        if field_type == "user_metadata":
            instrument_job.user_metadata.add(metadata_columns[i])
        else:
            instrument_job.user_metadata.add(metadata_columns[i])


def check_and_remove_metadata_from_map(i, metadata_columns, metadata_field_map):
    if metadata_columns[i].type in metadata_field_map:
        if metadata_columns[i].name in metadata_field_map[metadata_columns[i].type]:
            first_column = metadata_field_map[metadata_columns[i].type][metadata_columns[i].name][0]
            metadata_field_map[metadata_columns[i].type][metadata_columns[i].name].pop(0)
            if not metadata_field_map[metadata_columns[i].type][metadata_columns[i].name]:
                del metadata_field_map[metadata_columns[i].type][metadata_columns[i].name]

@job('export', timeout='3h')
def export_instrument_usage(instrument_ids: list[int], lab_group_ids: list[int], user_ids: list[int], mode: str, instance_id: str, time_started: str = None, time_ended: str = None, calculate_duration_with_cutoff: bool = False, user_id: int = 0, file_format: str = "xlsx", includes_maintenance: bool = False, approved_only: bool = True):
    instrument_usages = InstrumentUsage.objects.filter(instrument__id__in=instrument_ids)
    channel_layer = get_channel_layer()
    if mode == 'service_lab_group':
        lab_group = LabGroup.objects.filter(id__in=lab_group_ids, is_professional=True)
        if lab_group.exists():
            users = User.objects.filter(lab_groups__in=lab_group)
            instrument_jobs = InstrumentJob.objects.filter(service_lab_group__in=lab_group)
            instrument_usages = instrument_usages.filter(
                Q(user__in=users)|Q(annotation__instrument_jobs__in=instrument_jobs)
            )

        else:
            async_to_sync(channel_layer.group_send)(
                f"user_{user_id}_instrument_job",
                {
                    "type": "download_message",
                    "message": {
                        "instance_id": instance_id,
                        "status": "error",
                        "message": "Lab group not found"
                    },
                }
            )
            return
    elif mode == 'lab_group':
        lab_group = LabGroup.objects.filter(lab_group__id__in=lab_group_ids, is_professional=False)
        if lab_group.exists():
            users = User.objects.filter(lab_group__in=lab_group)
            instrument_usages = instrument_usages.filter(user__in=users)
        else:
            async_to_sync(channel_layer.group_send)(
                f"user_{user_id}_instrument_job",
                {
                    "type": "download_message",
                    "message": {
                        "instance_id": instance_id,
                        "status": "error",
                        "message": "Lab group not found"
                    },
                }
            )
            return
    else:
        if user_id != 0:
            instrument_usages = instrument_usages.filter(user__id__in=user_ids)

    instrument_usages = instrument_usages.filter(
        (Q(time_started__range=[time_started, time_ended]) |
        Q(time_ended__range=[time_started, time_ended]))
    )
    if not includes_maintenance:
        instrument_usages = instrument_usages.exclude(maintenance=True)
    if approved_only:
        instrument_usages = instrument_usages.filter(approved=True)

    if instrument_usages.exists():
        filename = str(uuid.uuid4())
        if time_started:
            time_started = timezone.make_aware(datetime.datetime.strptime(time_started, "%Y-%m-%dT%H:%M:%S.%fZ"))
        if time_ended:
            time_ended = timezone.make_aware(datetime.datetime.strptime(time_ended, "%Y-%m-%dT%H:%M:%S.%fZ"))
        if file_format == "xlsx":
            wb = Workbook()
            ws = wb.active
            ws.title = "instrument_usage"
            filename = filename + ".xlsx"
            filepath = os.path.join(settings.MEDIA_ROOT, "temp", filename)
        elif file_format == "csv" or file_format == "tsv":
            filename = filename + f".{file_format}"
            filepath = os.path.join(settings.MEDIA_ROOT, "temp", filename)
            infile = open(filepath, "wt", encoding="utf-8", newline="")
            if file_format == "csv":
                writer = csv.writer(infile)
            else:
                writer = csv.writer(infile, delimiter="\t")

        headers = ["Instrument", "User", "Time Started", "Time Ended", "Duration", "Description", "Associated Jobs", "Is Maintenance", "Is Approved"]
        if file_format == "xlsx":
            ws.append(headers)
        elif file_format == "csv" or file_format == "tsv":
            writer.writerow(headers)
        for i in instrument_usages:
            # check if instrument_usage time_started and time_ended are not splitted by the time_started and time_ended of the function
            duration = i.time_ended - i.time_started
            if calculate_duration_with_cutoff:
                if time_ended:
                    if i.time_ended > time_ended:
                        # calculate the duration within the boundary
                        if time_started:
                            if i.time_started <= time_started:
                                duration += time_ended - time_started
                            else:
                                duration += time_ended - i.time_started
                        else:
                            duration += time_ended - i.time_started
                    else:
                        if time_started:
                            if i.time_started <= time_started:
                                duration += i.time_ended - time_started
                            else:
                                duration += i.time_ended - i.time_started
                        else:
                            duration += i.time_ended - i.time_started
                else:
                    if time_started:
                        if i.time_started <= time_started:
                            duration += i.time_ended - time_started
                        else:
                            duration += i.time_ended - i.time_started
            associated_jobs_information = []
            if i.annotation:
                associated_jobs = i.annotation.assigned_instrument_jobs.all()
                for j in associated_jobs:
                    associated_jobs_information.append(f"{j.submitted_at} {j.job_name} ({j.user.username})")

            # convert time to string for excel
            exported_time_started = i.time_started.strftime("%Y-%m-%d")
            exported_time_ended = i.time_ended.strftime("%Y-%m-%d")
            exported_duration = duration.days+1
            if file_format == "xlsx":
                ws.append([i.instrument.instrument_name, i.user.username, exported_time_started, exported_time_ended, exported_duration, i.description, ";\n".join(associated_jobs_information), i.maintenance, i.approved])
            if file_format == "csv" or file_format == "tsv":
                writer.writerow([i.instrument.instrument_name, i.user.username, exported_time_started, exported_time_ended, exported_duration, i.description, ";".join(associated_jobs_information), i.maintenance, i.approved])
        if file_format == "xlsx":
            for col in ws.columns:
                max_length = 0
                column = col[0].column_letter
                for cell in col:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(cell.value)
                    except:
                        pass
                adjusted_width = (max_length + 2)
                ws.column_dimensions[column].width = adjusted_width

        if file_format == "xlsx":
            wb.save(filepath)
        signer = TimestampSigner()
        value = signer.sign(filename)
        async_to_sync(channel_layer.group_send)(
            f"user_{user_id}_instrument_job",
            {
                "type": "download_message",
                "message": {
                    "signed_value": value,
                    "instance_id": instance_id
                },
            }
        )
    else:
        async_to_sync(channel_layer.group_send)(
            f"user_{user_id}_instrument_job",
            {
                "type": "download_message",
                "message": {
                    "instance_id": instance_id,
                    "status": "error",
                    "message": "No instrument usage found"
                },
            }
        )

@job('export', timeout='3h')
def export_reagent_actions(start_date=None, end_date=None, storage_object_id=None,
                          user_id=None, export_format='csv', instance_id=None):
    """
    Export reagent actions within a specified time period with optional storage location filtering

    Args:
        start_date (datetime): Start date for filtering actions
        end_date (datetime): End date for filtering actions
        storage_object_id (int): Optional ID of storage object to filter by
        user_id (int): Optional user ID who requested the export
        export_format (str): Export format (currently only 'csv' supported)
        instance_id (str): Optional instance ID for tracking the job

    Returns:
        str: Signed filename for secure download
    """
    if not end_date:
        end_date = timezone.now()
    if not start_date:
        start_date = end_date - timedelta(days=30)

    actions_query = ReagentAction.objects.filter(
        created_at__gte=start_date,
        created_at__lte=end_date
    ).select_related('reagent', 'reagent__storage_object', 'user')

    if storage_object_id:
        try:
            storage_object = StorageObject.objects.get(id=storage_object_id)

            all_storage_objects = [storage_object]
            children = storage_object.get_all_children()
            all_storage_objects.extend(children)
            storage_ids = [obj.id for obj in all_storage_objects]

            actions_query = actions_query.filter(reagent__storage_object_id__in=storage_ids)
        except StorageObject.DoesNotExist:
            pass

    filename = f"reagent_actions_export_{uuid.uuid4().hex}.csv"
    export_dir = os.path.join(settings.MEDIA_ROOT, 'temp')

    os.makedirs(export_dir, exist_ok=True)
    filepath = os.path.join(export_dir, filename)

    with open(filepath, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)

        writer.writerow([
            'Date', 'Action Type', 'Reagent Name', 'Barcode', 'Barcode Format', 'Quantity',
            'Storage Location', 'Storage Path', 'User', 'Notes'
        ])

        for action in actions_query:
            storage_path = ""
            storage_obj = action.reagent.storage_object
            if storage_obj:
                path = storage_obj.get_path_to_root()
                storage_path = " > ".join([item["name"] for item in path])
            barcode_format = identify_barcode_format(action.reagent.barcode)
            writer.writerow([
                action.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                action.action_type,
                action.reagent.reagent.name,
                action.reagent.barcode or "",
                barcode_format,
                action.quantity if action.quantity else "",
                action.reagent.storage_object.object_name if action.reagent.storage_object else "",
                storage_path,
                action.user.username if action.user else "",
                action.notes or ""
            ])

    signer = TimestampSigner()
    signed_filename = signer.sign(filename)

    if user_id:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"user_{user_id}",
            {
                "type": "download_message",
                "message": {
                    "signed_value": signed_filename,
                    "instance_id": instance_id
                },
            }
        )
