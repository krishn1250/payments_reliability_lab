import pytest

from app.domain import (
    SignatureError,
    Status,
    can_transition,
    request_fingerprint,
    sign,
    verify_signature,
)

SECRET = "whsec_test"


class TestStateMachine:
    @pytest.mark.parametrize(
        "current,target",
        [(Status.PENDING, Status.SUCCEEDED), (Status.PENDING, Status.FAILED), (Status.SUCCEEDED, Status.REFUNDED)],
    )
    def test_allowed(self, current, target):
        assert can_transition(current, target)

    @pytest.mark.parametrize(
        "current,target",
        [
            (Status.PENDING, Status.REFUNDED),     # refund before success (out of order)
            (Status.FAILED, Status.SUCCEEDED),     # late success after failure
            (Status.SUCCEEDED, Status.FAILED),
            (Status.REFUNDED, Status.SUCCEEDED),
            (Status.SUCCEEDED, Status.SUCCEEDED),  # duplicate delivery
        ],
    )
    def test_rejected(self, current, target):
        assert not can_transition(current, target)


class TestFingerprint:
    def test_currency_case_does_not_matter(self):
        assert request_fingerprint(100, "inr", "c1") == request_fingerprint(100, "INR", "c1")

    def test_different_amount_differs(self):
        assert request_fingerprint(100, "INR", "c1") != request_fingerprint(101, "INR", "c1")


class TestSignature:
    body = b'{"event_id":"evt_1"}'

    def test_valid(self):
        verify_signature(SECRET, self.body, sign(SECRET, self.body, 1_000), now=1_010)

    def test_tampered_body(self):
        header = sign(SECRET, self.body, 1_000)
        with pytest.raises(SignatureError, match="mismatch"):
            verify_signature(SECRET, b'{"event_id":"evt_2"}', header, now=1_000)

    def test_wrong_secret(self):
        with pytest.raises(SignatureError):
            verify_signature(SECRET, self.body, sign("other", self.body, 1_000), now=1_000)

    def test_replay_outside_window(self):
        with pytest.raises(SignatureError, match="tolerance"):
            verify_signature(SECRET, self.body, sign(SECRET, self.body, 1_000), now=1_000 + 301)

    def test_timestamp_cannot_be_swapped(self):
        # Re-using an old v1 with a fresh t must fail, because t is signed.
        old = sign(SECRET, self.body, 1_000).split(",")[1]
        with pytest.raises(SignatureError, match="mismatch"):
            verify_signature(SECRET, self.body, f"t=2000,{old}", now=2_000)

    @pytest.mark.parametrize("header", [None, "", "garbage", "t=abc,v1=x", "v1=only"])
    def test_malformed(self, header):
        with pytest.raises(SignatureError):
            verify_signature(SECRET, self.body, header, now=1_000)
