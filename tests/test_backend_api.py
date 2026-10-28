"""Integration and unit tests for the MedPerplexity FastAPI backend platform."""

import json
import unittest
from tests import _paths  # noqa: F401
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.db import init_db, get_db_connection


class BackendPlatformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db(force_reseed=False)
        cls.client = TestClient(app)

    def test_health_check(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("MedPerplexity", data["engine"])

    def test_auth_login_success_and_failure(self):
        # 1. Invalid credentials
        bad_resp = self.client.post("/api/auth/login", json={
            "email": "dr.sharma@metrohealth.org",
            "password": "WrongPassword!"
        })
        self.assertEqual(bad_resp.status_code, 401)

        # 2. Valid credentials for Dr. Sharma
        good_resp = self.client.post("/api/auth/login", json={
            "email": "dr.sharma@metrohealth.org",
            "password": "DoctorPassword123!"
        })
        self.assertEqual(good_resp.status_code, 200)
        data = good_resp.json()
        self.assertIn("token", data)
        self.assertEqual(data["user"]["full_name"], "Dr. Priya Sharma, MD")
        self.assertEqual(data["user"]["role"], "doctor")
        self.assertEqual(data["user"]["specialty"], "Cardiology")
        self.assertEqual(data["user"]["organization"]["code"], "HOSP-METRO-01")

        # 3. Test /api/auth/me with Bearer token
        token = data["token"]
        me_resp = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(me_resp.status_code, 200)
        me_data = me_resp.json()
        self.assertEqual(me_data["user"]["email"], "dr.sharma@metrohealth.org")

    def test_unauthenticated_request_rejected(self):
        resp = self.client.get("/api/research/saved")
        self.assertEqual(resp.status_code, 401)

    def test_patients_list_and_detail(self):
        # Public or doctor route
        resp = self.client.get("/api/patients")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(data["count"], 15)
        self.assertTrue(any(p["patient_id"] == "PAT-001" for p in data["items"]))

        # Single patient detail
        p_resp = self.client.get("/api/patients/PAT-001")
        self.assertEqual(p_resp.status_code, 200)
        p_data = p_resp.json()
        self.assertEqual(p_data["patient_id"], "PAT-001")
        self.assertIn("aspirin", [a.lower() for a in p_data["allergies"]])

    def test_clinical_chat_and_persistence(self):
        # Sign in as Dr. Sharma
        login_resp = self.client.post("/api/auth/login", json={
            "email": "dr.sharma@metrohealth.org",
            "password": "DoctorPassword123!"
        })
        token = login_resp.json()["token"]

        # Run clinical chat: Ask about aspirin for PAT-001 (should trigger allergy block)
        chat_resp = self.client.post(
            "/api/patients/PAT-001/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "Prescribe Aspirin 75mg", "thread_id": "test-thread-1"}
        )
        self.assertEqual(chat_resp.status_code, 200)
        data = chat_resp.json()
        self.assertEqual(data["patient_id"], "PAT-001")
        self.assertEqual(data["response"]["status"], "blocked")
        self.assertIn("asm-", data["assessment_id"])

        # Check that it was persisted in /api/assessments
        hist_resp = self.client.get(
            "/api/assessments?patient_id=PAT-001",
            headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(hist_resp.status_code, 200)
        hist_items = hist_resp.json()["items"]
        self.assertTrue(any(it["id"] == data["assessment_id"] for it in hist_items))

    def test_research_search_and_saved_papers(self):
        login_resp = self.client.post("/api/auth/login", json={
            "email": "dr.sharma@metrohealth.org",
            "password": "DoctorPassword123!"
        })
        token = login_resp.json()["token"]

        # Search research (defaulting to Cardiology)
        res = self.client.get(
            "/api/research?specialty=Cardiology",
            headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(res.status_code, 200)
        r_data = res.json()
        self.assertGreaterEqual(r_data["count"], 1)
        self.assertTrue(any("35914999" in p["pmid"] or "Cardiology" in p.get("specialty", "") for p in r_data["papers"]))

        # Save a new paper
        save_resp = self.client.post(
            "/api/research/saved",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "pmid": "37213876",
                "title": "Renal Denervation and Antihypertensive Drug Optimization in Resistant Hypertension",
                "authors": "Kandzari DE et al.",
                "journal": "Lancet",
                "pub_date": "2023",
                "abstract": "SPYRAL HTN-ON MED 3-year outcomes.",
                "specialty": "Cardiology",
                "notes": "Reviewed for hypertension clinic."
            }
        )
        self.assertEqual(save_resp.status_code, 200)

        # Verify paper is in saved list
        saved_list = self.client.get("/api/research/saved", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(saved_list.status_code, 200)
        self.assertTrue(any(p["pmid"] == "37213876" for p in saved_list.json()["items"]))

        # Remove the paper
        del_resp = self.client.delete("/api/research/saved/37213876", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(del_resp.status_code, 200)

    def test_medication_catalog_search(self):
        login_resp = self.client.post("/api/auth/login", json={
            "email": "dr.sharma@metrohealth.org",
            "password": "DoctorPassword123!"
        })
        token = login_resp.json()["token"]

        res = self.client.get(
            "/api/medications/search?q=Telmisartan",
            headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertGreaterEqual(data["count"], 1)
        self.assertTrue(any("telmisartan" in m["generic_name"].lower() for m in data["items"]))

    def test_admin_authorization_boundaries(self):
        # 1. Doctor cannot access admin endpoints
        doc_login = self.client.post("/api/auth/login", json={
            "email": "dr.sharma@metrohealth.org",
            "password": "DoctorPassword123!"
        })
        doc_token = doc_login.json()["token"]

        forbidden_resp = self.client.get(
            "/api/admin/organization",
            headers={"Authorization": f"Bearer {doc_token}"}
        )
        self.assertEqual(forbidden_resp.status_code, 403)

        # 2. Admin CAN access admin endpoints
        admin_login = self.client.post("/api/auth/login", json={
            "email": "admin@metrohealth.org",
            "password": "AdminPassword123!"
        })
        admin_token = admin_login.json()["token"]

        admin_resp = self.client.get(
            "/api/admin/organization",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        self.assertEqual(admin_resp.status_code, 200)
        org_data = admin_resp.json()
        self.assertEqual(org_data["code"], "HOSP-METRO-01")
        self.assertIn("active_seats", org_data["stats"])


if __name__ == "__main__":
    unittest.main()

