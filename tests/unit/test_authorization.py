import unittest

from safety.access_control.authorization import (
    authorize_resource_access,
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


if __name__ == "__main__":
    unittest.main()