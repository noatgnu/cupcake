import hashlib
import io
import random
import string

from drf_chunked_upload.models import ChunkedUpload
import uuid
from cc.rq_tasks import import_user_data, export_user_data
from django.test import TestCase, Client
from rest_framework.authtoken.models import Token
from django.core.files.base import ContentFile
from django.test import TestCase
from cc.models import ProtocolModel, ProtocolSection, ProtocolStep, Reagent, StepReagent, ProtocolReagent, \
    AnnotationFolder, Annotation, Session, Tag, ProtocolTag, StepTag, Project
from rest_framework.test import APIClient
from cc.serializers import ProtocolModelSerializer, AnnotationFolderSerializer, AnnotationSerializer
from django.contrib.auth.models import User
import requests
# Create your tests here.
def create_random_user_data(user_id):
    # Get the user
    user = User.objects.get(id=user_id)

    # Create a random project
    project = Project.objects.create(project_name=''.join(random.choices(string.ascii_uppercase + string.digits, k=10)), owner=user)

    # Create a random session
    session = Session.objects.create(unique_id=uuid.uuid4().hex, user=user)

    # Create a random protocol
    protocol = ProtocolModel.objects.create(protocol_title=''.join(random.choices(string.ascii_uppercase + string.digits, k=10)), user=user, protocol_description="".join(random.choices(string.ascii_uppercase + string.digits, k=10)))

    # Create a random section
    section = ProtocolSection.objects.create(protocol=protocol, section_description=''.join(random.choices(string.ascii_uppercase + string.digits, k=10)))

    # Create a random step
    step = ProtocolStep.objects.create(protocol=protocol, step_section=section, step_description=''.join(random.choices(string.ascii_uppercase + string.digits, k=10))+"unit %1.unit%")

    # Create a random reagent
    reagent = Reagent.objects.create(name=''.join(random.choices(string.ascii_uppercase + string.digits, k=10)), unit='g')

    # Create a random protocol reagent
    protocol_reagent = ProtocolReagent.objects.create(protocol=protocol, reagent=reagent, quantity=random.uniform(1, 10))

    # Create a random step reagent
    step_reagent = StepReagent.objects.create(step=step, reagent=reagent, quantity=random.uniform(1, 10))

    # Create a random annotation folder
    annotation_folder = AnnotationFolder.objects.create(folder_name=''.join(random.choices(string.ascii_uppercase + string.digits, k=10)), session=session)

    # Create a random annotation
    annotation = Annotation.objects.create(session=session, step=step, annotation=''.join(random.choices(string.ascii_uppercase + string.digits, k=10)), folder=annotation_folder)

    # Create a random tag
    tag = Tag.objects.create(tag=''.join(random.choices(string.ascii_uppercase + string.digits, k=10)))

    # Create a random protocol tag
    protocol_tag = ProtocolTag.objects.create(protocol=protocol, tag=tag)

    # Create a random step tag
    step_tag = StepTag.objects.create(step=step, tag=tag)

    # add session to project
    project.sessions.add(session)

    return session, protocol, annotation, annotation_folder, reagent, protocol_reagent, step_reagent, protocol_tag, step_tag, project


class ProtocolViewSetTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='testuser', password='testpassword')
        self.token = self.user.auth_token
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

    def test_create_protocol(self):
        response = self.client.post(
            '/api/protocol/',
            {
                "url": "https://www.protocols.io/view/expression-and-purification-of-rab10-1-181-stoichi-4r3l24p1xg1y/v1?step=1"
            },
            format='json'
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(ProtocolModel.objects.count(), 1)
        self.assertEqual(ProtocolModel.objects.get().protocol_title, 'Test Protocol')

class ProtocolCloneTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='testuser', password='testpassword')
        self.token = self.user.auth_token
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
        self.session, self.protocol, self.annotation, self.annotation_folder, self.reagent, self.protocol_reagent, self.step_reagent, self.protocol_tag, self.step_tag, self.project = create_random_user_data(
            self.user.id)

    def test_clone_protocol(self):
        response = self.client.post(
            f'/api/protocol/{self.protocol.id}/clone/',
            {},
            format='json'
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(ProtocolModel.objects.count(), 2)
        self.assertEqual(ProtocolModel.objects.all()[1].protocol_title, ProtocolModel.objects.all()[0].protocol_title)
        print(response.json())


class ChunkedUploadViewTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='testuser', password='testpassword')
        self.token = self.user.auth_token
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

    def test_chunked_upload(self):
        file_content = b"test content"
        file = ContentFile(file_content, name='test.txt')

        with io.BytesIO(file_content) as f:
            chunk_size = 4
            current_url = None
            md5_hasher = hashlib.sha256()
            for i in range(0, len(file_content), chunk_size):
                f.seek(i)
                chunk = f.read(chunk_size)
                start_byte = i
                end_byte = start_byte + len(chunk) - 1
                total_size = len(file_content)
                content_range = f"bytes {start_byte}-{end_byte}/{total_size}"
                print(content_range)
                md5_hasher.update(chunk)
                # convert chunk to file like object
                chunk = ContentFile(chunk, name='test.txt')
                if current_url:
                    response = self.client.put(
                        current_url,
                        headers={"Authorization": f"Token {self.token}",
                                 "Content-Range": content_range},
                        data={"file": chunk, "filename": "test.txt"}, format='multipart'
                    )
                    current_url = response.json()["url"]
                else:
                    response = self.client.put(
                        '/api/chunked_upload/',
                        headers={"Authorization": f"Token {self.token}",
                                 "Content-Range": content_range},
                        data={"file": chunk, "filename": "test.txt"}, format='multipart'
                    )
                    current_url = response.json()["url"]
            hash = md5_hasher.hexdigest()
            response = self.client.post(
                current_url,
                headers={"Authorization": f"Token {self.token}"},
                data={"sha256": hash},
            )
            self.assertEqual(response.status_code, 200)

class ExportImportUserDataTestCase(TestCase):
    def setUp(self):
        user = User.objects.create_user(username='testuser', password='testpassword')
        # create random user data with session, protocol, annotation, annotation folder, reagent, protocol reagent and step reagent
        self.session, self.protocol, self.annotation, self.annotation_folder, self.reagent, self.protocol_reagent, self.step_reagent, self.protocol_tag, self.step_tag, self.project = create_random_user_data(user.id)

    def test_export_user_data(self):
        export_user_data(User.objects.all().first().id, 'data_test')
        # check if the file is created
        with open('data_test.tar.gz', 'rb') as f:
            self.assertTrue(f.read())

    def test_import_user_data(self):

        import_user_data(User.objects.all().first().id, 'data_test.tar.gz')
        # check if the data is imported
        self.assertEqual(Session.objects.count(), 2)
        self.assertEqual(ProtocolModel.objects.count(), 2)
        self.assertEqual(Annotation.objects.count(), 2)
        self.assertEqual(AnnotationFolder.objects.count(), 2)
        self.assertEqual(Reagent.objects.count(), 2)
        self.assertEqual(ProtocolReagent.objects.count(), 2)
        self.assertEqual(StepReagent.objects.count(), 2)
        self.assertEqual(ProtocolSection.objects.count(), 2)
        self.assertEqual(ProtocolStep.objects.count(), 2)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Project.objects.count(), 2)
        for p in Project.objects.all():
            print(p.sessions.all())


class IngredientsTestCase(TestCase):
    def setUp(self):
        # Create a random protocol
        self.protocol = ProtocolModel.objects.create(protocol_title='Test Protocol', protocol_description='Test Description',)

        # Create a random section
        self.section = ProtocolSection.objects.create(protocol=self.protocol, section_description='Test Section')

        # Create a random step
        self.step = ProtocolStep.objects.create(protocol=self.protocol, step_section=self.section,
                                        step_description='Test Step')

        # Create a random ingredient
        self.ingredient = Reagent.objects.create(name='Test Ingredient', unit='g')

    def test_ingredient_system(self):
        # Add the ingredient to the step with a random quantity
        initial_quantity = random.uniform(1, 10)
        step = StepReagent.objects.create(step=self.step, ingredient=self.ingredient, quantity=initial_quantity)

        pin = ProtocolReagent.objects.create(protocol=self.step.protocol, ingredient=self.ingredient,
                                             quantity=step.quantity)

        # Assert that the ingredient is added to the step
        self.assertEqual(self.step.reagents.count(), 1)
        self.assertEqual(self.step.reagents.first().quantity, initial_quantity)

        # Update the quantity of the ingredient in the step
        new_quantity = random.uniform(1, 10)
        step_ingredient = self.step.reagents.first()
        before_quantity = pin.quantity - step_ingredient.quantity
        step_ingredient.quantity = new_quantity
        step_ingredient.save()
        pin.quantity = before_quantity + new_quantity
        pin.save()

        # Assert that the quantity is updated
        self.assertEqual(self.step.reagents.first().quantity, new_quantity)

        # Assert that the protocol ingredient quantity is updated
        protocol_ingredient = ProtocolReagent.objects.get(protocol=self.protocol, ingredient=self.ingredient)
        self.assertEqual(protocol_ingredient.quantity, new_quantity)

class AnnotationFolderSystemTestCase(TestCase):
    def setUp(self):
        user = User.objects.create_user(username='testuser', password='testpassword')
        # Create a random session
        self.session = Session.objects.create(unique_id=uuid.uuid4().hex, user=user)

        # Create a random annotation
        self.annotation = Annotation.objects.create(session=self.session, annotation='Test Annotation')

        # Create random annotation folders
        self.folder1 = AnnotationFolder.objects.create(folder_name='Test Folder 1', session=self.session)
        self.folder2 = AnnotationFolder.objects.create(folder_name='Test Folder 2', session=self.session)

    def test_annotation_folder_system(self):
        # Move the annotation to folder1
        self.annotation.folder = self.folder1
        self.annotation.save()

        # Assert that the annotation is in folder1
        self.assertEqual(self.annotation.folder, self.folder1)

        # Move the annotation to folder2
        self.annotation.folder = self.folder2
        self.annotation.save()

        # Assert that the annotation is in folder2
        self.assertEqual(self.annotation.folder, self.folder2)
        # Move folder1 to folder2
        self.folder1.parent_folder = self.folder2
        self.folder1.save()
        # Assert that folder1 is in folder2
        self.assertEqual(self.folder1.parent_folder, self.folder2)

        # test serialize folder
        serialized = AnnotationFolderSerializer(self.folder1, many=False).data
        assert serialized["folder_name"] == self.folder1.folder_name

        serializedAnnotation = AnnotationSerializer(self.annotation, many=False).data
        assert len(serializedAnnotation["folder"]) == 1
        assert serializedAnnotation["folder"][0]["id"] == self.folder2.id
        assert serializedAnnotation["folder"][0]["folder_name"] == self.folder2.folder_name


        # test delete folder
        self.folder1.delete()
        assert self.folder2.child_folders.all().count() == 0


class TestProtocolsIOModel(TestCase):
    def setUp(self):
        User.objects.create_user(username="test", password="test")

    def test_create_protocol_from_url(self):
        resp = self.client.post(
            '/api/token-auth/',
            {"username": "test", "password": "test"})
        token = resp.json()["token"]
        resp = self.client.post(
            '/api/protocol/',
            {"url": "https://www.protocols.io/view/expression-and-purification-of-rab10-1-181-stoichi-4r3l24p1xg1y/v1?step=1"}, headers={"Authorization": f"Token {token}"}
        )
        resp_data = resp.json()
        protocol_section = self.client.post(
            '/api/section/',
            {"protocol": resp_data["id"], "section_description": "test", "section_duration": 0}, headers={"Authorization": f"Token {token}"}
        )

        assert protocol_section.status_code == 201

        # test update section

        resp_section_update = self.client.patch(
            f'/api/section/{protocol_section.json()["id"]}/',
            {"section_description": "test1", "section_duration": 1}, headers={"Authorization": f"Token {token}"}, content_type="application/json"
        )
        print(resp_section_update.content)
        assert resp_section_update.status_code == 200
        assert resp_section_update.json()["section_description"] == "test1"

        # test add step
        resp = self.client.post(
            '/api/step/',
            {
                "protocol": resp_data["id"],
                "step_description": "test",
                "step_section": protocol_section.json()["id"], "step_duration": 1}, headers={"Authorization": f"Token {token}"}
        )
        assert resp.status_code == 201
        resp_data1 = resp.json()
        assert resp_data1["step_description"] == "test"
        assert resp_data1["step_section"] == protocol_section.json()["id"]
        assert resp_data1["step_duration"] == 1


        # test create session
        resp_session = self.client.post(
            '/api/session/',
            {"user": 1}, headers={"Authorization": f"Token {token}"}
        )
        assert resp_session.status_code == 201

        # test first step move up

        resp_step_move_up = self.client.patch(
            f'/api/step/2/move_up/',
            headers={"Authorization": f"Token {token}"}
        )

        assert resp_step_move_up.status_code == 200
        print(resp_step_move_up.json()["next_step"])

        # test second step move down
        resp_step_move_down = self.client.patch(
            f'/api/step/4/move_down/',
            headers={"Authorization": f"Token {token}"}
        )

        assert resp_step_move_down.status_code == 200
        print(resp_step_move_down.json()["next_step"])


        # test create annotation with file
        c = ContentFile(b"test", "test.txt")

        resp_annotation = self.client.post(
            '/api/annotation/',
            {"step": resp_data1["id"], "session": resp_session.json()["unique_id"], "annotation": "test", "file": c, "annotation_type": "file"}, headers={"Authorization": f"Token {token}"})

        assert resp_annotation.status_code == 201

        delete_file = self.client.delete(
            f'/api/annotation/{resp_annotation.json()["id"]}/',
            headers={"Authorization": f"Token {token}"}
        )


        assert delete_file.status_code == 204
        # test delete section
        resp_section_delete = self.client.delete(
            f'/api/section/1/',
            headers={"Authorization": f"Token {token}"}
        )
        assert resp_section_delete.status_code == 204
        # check if number of steps decreased
        resp_after_section_delete = self.client.get(
            f'/api/protocol/{resp_data["id"]}/',
            headers={"Authorization": f"Token {token}"}
        )
        assert len(resp_after_section_delete.json()["steps"]) < 70




        # test create timekeeper
        resp = self.client.post(
            '/api/timekeeper/',
            {"session": resp_session.json()["unique_id"], "step": resp_data1["id"]}, headers={"Authorization": f"Token {token}"}
        )

        assert resp.status_code == 201 or resp.status_code == 200

        # test get timekeeper duplicate

        resp_timekeeper_from_step = self.client.post(
            f'/api/timekeeper/', {"session": resp_session.json()["unique_id"], "step": resp_data1["id"]},
            headers={"Authorization": f"Token {token}"}
        )

        assert resp_timekeeper_from_step.status_code != 200

        # test delete step
        resp = self.client.delete(
            f'/api/step/{resp_data1["id"]}/',
            headers={"Authorization": f"Token {token}"}
        )
        assert resp.status_code == 204

        # test delete
        resp = self.client.delete(
            f'/api/protocol/{resp_data["id"]}/',
            headers={"Authorization": f"Token {token}"}
        )
        assert resp.status_code == 204


class TestSession(TestCase):
    def setUp(self):
        User.objects.create_user(username="test", password="test")

    def test_session(self):
        resp = self.client.post(
            '/api/token-auth/',
            {"username": "test", "password": "test"})
        token = resp.json()["token"]
        resp = self.client.post(
            '/api/session/',
            {"user": 1}, headers={"Authorization": f"Token {token}"}
        )
        assert resp.status_code == 201
        assert "unique_id" in resp.json()
        assert "id" in resp.json()

        resp = self.client.get(
            f'/api/session/{resp.json()["unique_id"]}/',
            headers={"Authorization": f"Token {token}"}
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == 1




