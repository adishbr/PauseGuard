
import unittest

from safety.access_control.authorization import (
    authorize_resource_access,
    VALID_ROLES,
)


class TestAuthorization(unittest.TestCase):

    def test_owner_with_allowed_role_is_authorized(self):
        self.assertTrue(
            authorize_resource_access(
                "user-1", "payer", "user-1", {"payer"}
            )
        )

    def test_different_user_is_rejected(self):
        self.assertFalse(
            authorize_resource_access(
                "user-2", "payer", "user-1", {"payer"}
            )
        )

    def test_disallowed_role_is_rejected(self):
        self.assertFalse(
            authorize_resource_access(
                "user-1", "guardian", "user-1", {"payer"}
            )
        )

    def test_unknown_role_is_rejected(self):
        self.assertFalse(
            authorize_resource_access(
                "user-1", "superuser", "user-1", {"superuser"}
            )
        )

    def test_empty_actor_id_is_rejected(self):
        self.assertFalse(
            authorize_resource_access(
                "", "payer", "user-1", {"payer"}
            )
        )

    def test_empty_owner_id_is_rejected(self):
        self.assertFalse(
            authorize_resource_access(
                "user-1", "payer", "", {"payer"}
            )
        )

    def test_invalid_allowed_roles_type_is_rejected(self):
        self.assertFalse(
            authorize_resource_access(
                "user-1", "payer", "user-1", ["payer"]
            )
        )

    def test_invalid_allowed_role_is_rejected(self):
        self.assertFalse(
            authorize_resource_access(
                "user-1", "payer", "user-1", {"superuser"}
            )
        )

    # Additional edge-case and negative tests

    def test_guardian_owner_with_allowed_role_is_authorized(self):
        self.assertTrue(
            authorize_resource_access(
                "guardian-1", "guardian", "guardian-1",
                {"guardian"},
            )
        )

    def test_admin_owner_with_allowed_role_is_authorized(self):
        self.assertTrue(
            authorize_resource_access(
                "admin-1", "admin", "admin-1", {"admin"}
            )
        )

    def test_all_valid_roles_are_recognized(self):
        self.assertEqual(
            VALID_ROLES,
            {"payer", "guardian", "admin"},
        )

    def test_whitespace_actor_id_is_rejected(self):
        self.assertFalse(
            authorize_resource_access(
                "   ", "payer", "user-1", {"payer"}
            )
        )

    def test_whitespace_actor_role_is_rejected(self):
        self.assertFalse(
            authorize_resource_access(
                "user-1", "   ", "user-1", {"payer"}
            )
        )

    def test_whitespace_owner_id_is_rejected(self):
        self.assertFalse(
            authorize_resource_access(
                "user-1", "payer", "   ", {"payer"}
            )
        )

    def test_none_actor_id_is_rejected(self):
        self.assertFalse(
            authorize_resource_access(
                None, "payer", "user-1", {"payer"}
            )
        )

    def test_none_allowed_roles_is_rejected(self):
        self.assertFalse(
            authorize_resource_access(
                "user-1", "payer", "user-1", None
            )
        )

    def test_empty_allowed_roles_is_rejected(self):
        self.assertFalse(
            authorize_resource_access(
                "user-1", "payer", "user-1", set()
            )
        )

    def test_role_matching_is_case_sensitive(self):
        self.assertFalse(
            authorize_resource_access(
                "user-1", "PAYER", "user-1", {"payer"}
            )
        )

    def test_owner_matching_is_exact(self):
        self.assertFalse(
            authorize_resource_access(
                "User-1", "payer", "user-1", {"payer"}
            )
        )

    def test_multiple_valid_allowed_roles_work(self):
        self.assertTrue(
            authorize_resource_access(
                "user-1", "payer", "user-1",
                {"payer", "guardian", "admin"},
            )
        )

    def test_mixed_valid_and_invalid_allowed_roles_are_rejected(self):
        self.assertFalse(
            authorize_resource_access(
                "user-1", "payer", "user-1",
                {"payer", "superuser"},
            )
        )


if __name__ == "__main__":
    unittest.main()
