"""Place names from the PSGC lists choose the Concentrix site."""

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from bulk_upload import clearly_non_ph, in_upload_window
from ph_locations import nearest_site

MANILA = ZoneInfo("Asia/Manila")


def site(location: str) -> str:
    return nearest_site(location)[0]


class PhilippineSites(unittest.TestCase):
    def test_city_beats_a_shared_district_name(self):
        self.assertEqual(site("San Andres Cainta"), "2026 Bridgetowne Campaign")
        self.assertEqual(site("Cainta, Rizal"), "2026 Bridgetowne Campaign")
        self.assertEqual(site("Polomolok, South Cotabato"), "2026 Davao Campaign")
        self.assertEqual(site("Poblacion, Makati"), "2026 Makati G5 Campaign")
        self.assertEqual(site("Poblacion"), "2026 Bridgetowne Campaign")

    def test_province_picks_the_city_when_the_name_is_shared(self):
        self.assertEqual(site("San Fernando, Pampanga"), "2026 Clark Campaign")
        self.assertEqual(site("San Fernando, La Union"), "2026 Baguio Campaign")
        self.assertEqual(site("San Fernando"), "2026 Bridgetowne Campaign")
        self.assertEqual(site("San Quintin, Pangasinan"), "2026 Baguio Campaign")
        self.assertEqual(site("San Quintin"), "2026 Baguio Campaign")
        self.assertEqual(site("Santa Rosa, Laguna"), "2026 Nuvali Campaign")
        self.assertEqual(site("Naga City, Camarines Sur"), "2026 Naga Campaign")
        self.assertEqual(site("Naga, Cebu"), "2026 Cebu IT Park Campaign")
        self.assertEqual(site("Isabela"), "2026 Baguio Campaign")
        self.assertEqual(site("Isabela City"), "2026 CDO Campaign")
        self.assertEqual(site("Quezon, Isabela"), "2026 Baguio Campaign")
        self.assertEqual(site("Iba, Zambales"), "2026 Clark Campaign")

    def test_ncr_and_landmarks(self):
        self.assertEqual(site("Manila"), "2026 San Lazaro Campaign")
        self.assertEqual(site("Sampaloc, Manila"), "2026 San Lazaro Campaign")
        self.assertEqual(site("Quezon City"), "2026 Eton Campaign")
        self.assertEqual(site("Cubao, Quezon City"), "2026 Spark Campaign")
        self.assertEqual(site("Fairview, Quezon City"), "2026 UP Ayala Technohub Campaign")
        self.assertEqual(site("Eastwood"), "2026 Eastwood Campaign")
        self.assertEqual(site("Pasig"), "2026 Bridgetowne Campaign")
        self.assertEqual(site("Ortigas, Pasig"), "2026 Megamall Campaign")
        self.assertEqual(site("Makati"), "2026 Makati G5 Campaign")
        self.assertEqual(site("BGC, Taguig"), "2026 Taguig Campaign")
        self.assertEqual(site("Caloocan"), "2026 Cyberwest Campaign")
        self.assertEqual(site("Las Pinas"), "2026 Alabang Campaign")
        self.assertEqual(site("Fairview, Davao"), "2026 Davao Campaign")
        self.assertEqual(site("Metro Manila"), "2026 Bridgetowne Campaign")
        self.assertEqual(site("Sta. Mesa, Manila"), "2026 San Lazaro Campaign")
        self.assertEqual(site("Sta Mesa"), "2026 San Lazaro Campaign")
        self.assertEqual(site("San Andres Bukid Manila"), "2026 San Lazaro Campaign")
        self.assertEqual(site("Para\u5e3daque"), "2026 MOA Campaign")
        self.assertEqual(site("Ozamiz City"), "2026 CDO Campaign")
        self.assertEqual(site("Naga City"), "2026 Naga Campaign")
        self.assertEqual(site("San Felipe, Naga City"), "2026 Naga Campaign")
        self.assertEqual(site("Rodriquez"), "2026 UP Ayala Technohub Campaign")
        self.assertEqual(site("Bukindon"), "2026 CDO Campaign")
        self.assertEqual(site("Cagayab de Oro City"), "2026 CDO Campaign")
        self.assertEqual(site("Bicol"), "2026 Naga Campaign")
        self.assertEqual(site("Bagumbayan, Taguig"), "2026 Taguig Campaign")
        self.assertEqual(site("San Juan, Taytay, Rizal"), "2026 Bridgetowne Campaign")
        self.assertEqual(site("Porac, Pampanga"), "2026 Clark Campaign")
        self.assertEqual(site("Davao City, Philippines"), "2026 Davao Campaign")
        self.assertEqual(site("Quezon City, Philippines"), "2026 Eton Campaign")
        self.assertEqual(site("Makati City, Philippines"), "2026 Makati G5 Campaign")
        self.assertEqual(site("Bacolod City, Philippines"), "2026 Bacolod Campaign")
        self.assertEqual(site("Dagami, Leyte / Mandaue City"), "2026 Cebu J Center Campaign")
        self.assertEqual(site("Anges City"), "2026 Clark Campaign")
        self.assertEqual(site("Talisay City, Negros Occidental"), "2026 Bacolod Campaign")
        self.assertEqual(site("Sta. Cruz, Laguna"), "2026 Nuvali Campaign")
        self.assertEqual(site("Tambo, Samal, Davao del Norte"), "2026 Davao Campaign")
        self.assertEqual(site("Samal, Bataan"), "2026 Clark Campaign")
        self.assertEqual(site("Island Garden City of Samal"), "2026 Davao Campaign")

    def test_provinces_and_known_cities(self):
        cases = {
            "Cebu": "2026 Cebu IT Park Campaign",
            "Lapu-Lapu": "2026 Cebu Mactan Campaign",
            "Mandaue": "2026 Cebu J Center Campaign",
            "Antipolo": "2026 Eastwood Campaign",
            "Rodriguez, Rizal": "2026 UP Ayala Technohub Campaign",
            "Montalban": "2026 UP Ayala Technohub Campaign",
            "Binangonan": "2026 Bridgetowne Campaign",
            "Gingoog City": "2026 CDO Campaign",
            "Cagayan de Oro": "2026 CDO Campaign",
            "Cagayan": "2026 Baguio Campaign",
            "Davao": "2026 Davao Campaign",
            "General Santos": "2026 Davao Campaign",
            "CDO": "2026 CDO Campaign",
            "Gensan": "2026 Davao Campaign",
            "QC": "2026 Eton Campaign",
            "Iloilo": "2026 Ilo-Ilo Campaign",
            "Bacolod": "2026 Bacolod Campaign",
            "Palawan": "2026 Nuvali Campaign",
            "Butuan": "2026 CDO Campaign",
            "Tuguegarao": "2026 Baguio Campaign",
            "Angeles, Pampanga": "2026 Clark Campaign",
            "Ligao City": "2026 Naga Campaign",
            "Buenavista, Guimaras": "2026 Ilo-Ilo Campaign",
            "Kibawe, Bukidnon": "2026 CDO Campaign",
            "Tarlac City": "2026 Clark Campaign",
            "Lucena, Quezon": "2026 Nuvali Campaign",
            "Quezon": "2026 Nuvali Campaign",
            "Brgy. Ibabang Bukal, Tayabas City, Quezon": "2026 Nuvali Campaign",
            "Surigao City": "2026 CDO Campaign",
            "Philippines": "2026 Bridgetowne Campaign",
            "Not Specified": "2026 Bridgetowne Campaign",
            "Work From Home": "2026 Work At Home Campaign",
        }
        for location, expected in cases.items():
            self.assertEqual(site(location), expected, location)

    def test_ids_stay_the_portal_ids(self):
        self.assertEqual(nearest_site("Polomolok, South Cotabato")[1], "535")
        self.assertEqual(nearest_site("Cainta")[1], "522")
        self.assertEqual(nearest_site("Lapu-Lapu City")[1], "532")

    def test_ambiguous_philippine_addresses_use_bridgetowne(self):
        self.assertEqual(nearest_site(""), ("2026 Bridgetowne Campaign", "522"))
        self.assertEqual(nearest_site("N/A"), ("2026 Bridgetowne Campaign", "522"))
        self.assertEqual(nearest_site("Philippines"), ("2026 Bridgetowne Campaign", "522"))
        self.assertEqual(nearest_site("Cebu City"), ("2026 Cebu IT Park Campaign", "528"))
        self.assertEqual(nearest_site("wah north"), ("2026 Work At Home Campaign | BM NORTH", "554"))
        self.assertEqual(nearest_site("bm north"), ("2026 Work At Home Campaign | BM NORTH", "554"))
        self.assertEqual(nearest_site("work at home north"), ("2026 Work At Home Campaign | BM NORTH", "554"))
        self.assertEqual(nearest_site("bm south"), ("2026 Work At Home Campaign | BM SOUTH", "555"))
        self.assertEqual(nearest_site("wah south"), ("2026 Work At Home Campaign | BM SOUTH", "555"))
        self.assertEqual(nearest_site("work at home south"), ("2026 Work At Home Campaign | BM SOUTH", "555"))
        self.assertEqual(nearest_site("wah"), ("2026 Work At Home Campaign", "553"))
        self.assertEqual(nearest_site("work at home"), ("2026 Work At Home Campaign", "553"))
        self.assertEqual(nearest_site("work from home"), ("2026 Work At Home Campaign", "553"))

    def test_foreign_locations_stay_invalid(self):
        # bulk_upload marks these INVALID before nearest_site, so they are not Bridgetowne.
        for location in ("Nigeria", "India", "Dubai", "Houston", "Kuala Lumpur", "Japan"):
            self.assertTrue(clearly_non_ph(location), location)

    def test_upload_window_runs_through_3am(self):
        def at(hour):
            return in_upload_window(datetime(2026, 11, 4, hour, 30, tzinfo=MANILA))

        for hour in (8, 12, 23, 0, 1, 2, 3):
            self.assertTrue(at(hour), hour)
        for hour in (4, 5, 6, 7):
            self.assertFalse(at(hour), hour)


if __name__ == "__main__":
    unittest.main()
