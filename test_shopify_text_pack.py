"""
Unit tests for the Shopify Text-Only pack: the /webhooks/shopify/orders webhook
grants the text_only Keyhole package for orders carrying the Text-Only variant
(or its SKU), once per order id, without disturbing picture-pack handling.

Variant ids are resolved live from the storefront (they change when a variant is
recreated), so these tests stub _text_only_variant instead of hitting the network.
"""

import base64
import hashlib
import hmac as hmac_mod
import json
import unittest
from unittest.mock import MagicMock, patch

import main


def _signed_headers(raw: bytes, secret: str) -> dict:
    digest = base64.b64encode(hmac_mod.new(secret.encode(), raw, hashlib.sha256).digest()).decode()
    return {"X-Shopify-Hmac-Sha256": digest}


def _order(order_id, line_items, email="buyer@example.com", attrs=None):
    return {
        "id": order_id,
        "email": email,
        "contact_email": email,
        "line_items": line_items,
        "note_attributes": [{"name": "lockeddoor_user", "value": v} for v in (attrs or [])],
    }


class TestTextOnlyVariantResolution(unittest.TestCase):

    def setUp(self):
        main._TEXT_ONLY_CACHE.update({"variant_id": "", "sku": "", "price": "", "resolved_at": 0.0})

    def test_resolves_live_variant_from_storefront(self):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"variants": [{"id": 44898187903066, "sku": None, "price": "5.99", "available": True}]}
        with patch.object(main.requests, "get", return_value=resp) as get:
            ids = main._text_only_variant()
        self.assertEqual(ids["variant_id"], "44898187903066")
        self.assertEqual(ids["price"], "5.99")
        self.assertEqual(ids["sku"], main.TEXT_ONLY_SKU)   # product has no SKU yet: fallback
        self.assertIn("/products/text-only.js", get.call_args[0][0])

    def test_cache_prevents_refetch(self):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"variants": [{"id": 111, "sku": "X", "price": "5.99"}]}
        with patch.object(main.requests, "get", return_value=resp) as get:
            main._text_only_variant()
            main._text_only_variant()
        self.assertEqual(get.call_count, 1)

    def test_falls_back_to_configured_when_storefront_down(self):
        with patch.object(main.requests, "get", side_effect=Exception("boom")):
            ids = main._text_only_variant()
        self.assertEqual(ids["variant_id"], main.TEXT_ONLY_VARIANT_ID)
        self.assertEqual(ids["sku"], main.TEXT_ONLY_SKU)

    def test_cart_url_uses_resolved_variant(self):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"variants": [{"id": 44898187903066, "sku": None, "price": "5.99"}]}
        with patch.object(main.requests, "get", return_value=resp):
            url = main._text_only_cart_url()
        self.assertEqual(url, "https://lockeddoorai.myshopify.com/cart/44898187903066:1?channel=web")


class TestShopifyTextOnlyGrant(unittest.TestCase):

    def setUp(self):
        # Pin the resolved ids so webhook tests are deterministic offline.
        p = patch.object(main, "_text_only_variant", return_value={
            "variant_id": main.TEXT_ONLY_VARIANT_ID,
            "sku": main.TEXT_ONLY_SKU,
            "price": "5.99",
            "resolved_at": 0.0,
        })
        p.start()
        self.addCleanup(p.stop)

    @patch.object(main, "_user_for_email", return_value={"user_id": "usr_text"})
    @patch.object(main, "_fulfil_keyhole_payment")
    @patch.object(main, "SHOPIFY_WEBHOOK_SECRET", "test-secret")
    def test_text_variant_grants_text_only(self, fulfil, _email):
        fulfil.return_value = {"ok": True, "package": "text_only"}
        order = _order(901, [{"quantity": 1, "variant_id": main.TEXT_ONLY_VARIANT_ID, "sku": None}])
        raw = json.dumps(order).encode()
        res = main.ShopifyPaymentProvider().process_webhook(raw, _signed_headers(raw, "test-secret"))
        fulfil.assert_called_once()
        args = fulfil.call_args[0]
        self.assertEqual(args[0], "shopify")
        self.assertEqual(args[1], "shopify:text:901")
        self.assertEqual(args[2], "text_only")
        self.assertEqual(res.get("package"), "text_only")

    @patch.object(main, "_user_for_email", return_value={"user_id": "usr_text"})
    @patch.object(main, "_fulfil_keyhole_payment")
    @patch.object(main, "SHOPIFY_WEBHOOK_SECRET", "test-secret")
    def test_text_sku_grants_text_only(self, fulfil, _email):
        fulfil.return_value = {"ok": True, "package": "text_only"}
        order = _order(902, [{"quantity": 2, "sku": main.TEXT_ONLY_SKU}])
        raw = json.dumps(order).encode()
        main.ShopifyPaymentProvider().process_webhook(raw, _signed_headers(raw, "test-secret"))
        self.assertEqual(fulfil.call_args[0][2], "text_only")

    @patch.object(main, "_user_for_email", return_value={"user_id": "usr_text"})
    @patch.object(main, "_grant_picture_packs")
    @patch.object(main, "SHOPIFY_WEBHOOK_SECRET", "test-secret")
    def test_picture_pack_still_grants_pictures(self, grant, _email):
        grant.return_value = {"ok": True, "pic_credits": 5}
        order = _order(903, [{"quantity": 1, "sku": main.PICTURE_PACK_SKU}])
        raw = json.dumps(order).encode()
        main.ShopifyPaymentProvider().process_webhook(raw, _signed_headers(raw, "test-secret"))
        grant.assert_called_once()
        self.assertEqual(grant.call_args[0][1], 1)

    @patch.object(main, "SHOPIFY_WEBHOOK_SECRET", "test-secret")
    def test_other_products_ignored(self):
        order = _order(904, [{"quantity": 3, "sku": "SHIRT-L"}])
        raw = json.dumps(order).encode()
        res = main.ShopifyPaymentProvider().process_webhook(raw, _signed_headers(raw, "test-secret"))
        self.assertTrue(res.get("ignored"))

    @patch.object(main, "SHOPIFY_WEBHOOK_SECRET", "test-secret")
    def test_bad_signature_rejected(self):
        order = _order(905, [{"quantity": 1, "variant_id": main.TEXT_ONLY_VARIANT_ID}])
        raw = json.dumps(order).encode()
        headers = _signed_headers(raw, "test-secret")
        headers["X-Shopify-Hmac-Sha256"] = base64.b64encode(b"wrong").decode()
        from fastapi.exceptions import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            main.ShopifyPaymentProvider().process_webhook(raw, headers)
        self.assertEqual(ctx.exception.status_code, 401)

    @patch.object(main, "SHOPIFY_WEBHOOK_SECRET", "test-secret")
    def test_mixed_order_prioritizes_text_then_pictures(self):
        with patch.object(main, "_user_for_email", return_value={"user_id": "usr_text"}), \
             patch.object(main, "_fulfil_keyhole_payment") as fulfil:
            fulfil.return_value = {"ok": True, "package": "text_only"}
            order = _order(906, [
                {"quantity": 1, "variant_id": main.TEXT_ONLY_VARIANT_ID},
                {"quantity": 1, "sku": main.PICTURE_PACK_SKU},
            ], attrs=["usr_attr.abc"])
            raw = json.dumps(order).encode()
            main.ShopifyPaymentProvider().process_webhook(raw, _signed_headers(raw, "test-secret"))
            self.assertEqual(fulfil.call_args[0][2], "text_only")

    def test_helper_matches_variant_and_sku_only(self):
        self.assertTrue(main._is_text_only_line({"variant_id": main.TEXT_ONLY_VARIANT_ID}))
        self.assertTrue(main._is_text_only_line({"sku": main.TEXT_ONLY_SKU.lower()}))
        self.assertFalse(main._is_text_only_line({"variant_id": "999", "sku": "NOPE"}))
        self.assertFalse(main._is_text_only_line({}))


if __name__ == "__main__":
    unittest.main()
