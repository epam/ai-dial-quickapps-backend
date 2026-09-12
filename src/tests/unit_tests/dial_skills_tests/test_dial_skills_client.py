from types import SimpleNamespace
from typing import cast

import pytest
from aidial_client import AsyncDial

from quickapp.dial_skills._dial_skills_client import _DialSkillsClient
from quickapp.dial_skills._exceptions import (
    DialSkillFileNotTextError,
    DialSkillFileReadError,
    DialSkillFileTooLargeError,
)
from quickapp.dial_skills._settings import DialSkillsSettings

SKILL_URL = "skills/my-bucket/refund-policy"
FILES_PREFIX = f"{SKILL_URL}/files/"


def _page(urls: list[str], next_token: str | None = None) -> SimpleNamespace:
    """A stand-in for the client's SkillFileMetadata page."""
    return SimpleNamespace(
        url=FILES_PREFIX,
        next_token=next_token,
        items=[SimpleNamespace(url=url) for url in urls],
    )


class _FakeFilesRef:
    """The tail of ``client.skills(url=...).files(path=...)``.

    Hand-written rather than a MagicMock chain: ``skill.files.list()`` and
    ``skill.files(path=...).read()`` land on *different* auto-created mocks,
    so a fixture that stubs one silently fails to intercept the other. The
    signatures mirror the real reference, so a drift shows up as a TypeError.
    """

    def __init__(self, recorder: "_FakeSkills", url: str, path: str | None = None):
        self._recorder = recorder
        self._url = url
        self._path = path

    def __call__(self, *, path: str) -> "_FakeFilesRef":
        return _FakeFilesRef(self._recorder, self._url, path)

    async def list(
        self,
        *,
        limit: int | None = None,
        token: str | None = None,
        recursive: bool | None = None,
    ) -> SimpleNamespace:
        self._recorder.list_calls.append({"url": self._url, "token": token, "recursive": recursive})
        pages = self._recorder.pages
        return pages[min(len(self._recorder.list_calls) - 1, len(pages) - 1)]

    async def read(self) -> SimpleNamespace:
        self._recorder.read_calls.append((self._url, self._path))
        if self._recorder.read_error is not None:
            raise self._recorder.read_error

        async def aget_content() -> bytes:
            return self._recorder.content

        return SimpleNamespace(aget_content=aget_content)


class _FakeSkillRef:
    def __init__(self, recorder: "_FakeSkills", url: str):
        self._recorder = recorder
        self._url = url

    @property
    def files(self) -> _FakeFilesRef:
        return _FakeFilesRef(self._recorder, self._url)


class _FakeSkills:
    """Stands in for ``AsyncDial.skills`` and records what was asked for."""

    def __init__(self, pages: list[SimpleNamespace], content: bytes):
        self.pages = pages
        self.content = content
        self.read_error: BaseException | None = None
        self.list_calls: list[dict[str, object]] = []
        self.read_calls: list[tuple[str, str | None]] = []

    def __call__(self, *, url: str) -> _FakeSkillRef:
        return _FakeSkillRef(self, url)


def _make_client(
    *,
    pages: list[SimpleNamespace] | None = None,
    content: bytes = b"hello",
    settings: DialSkillsSettings | None = None,
) -> tuple[_DialSkillsClient, _FakeSkills]:
    skills = _FakeSkills(pages or [_page([])], content)
    dial_client = cast(AsyncDial, SimpleNamespace(skills=skills))
    client = _DialSkillsClient(dial_client, settings or DialSkillsSettings())
    return client, skills


class TestListTextFiles:

    @pytest.mark.asyncio
    async def test_advertises_only_text_files(self):
        client, _ = _make_client(
            pages=[
                _page(
                    [
                        f"{FILES_PREFIX}SKILL.md",
                        f"{FILES_PREFIX}references/eu-rules.md",
                        f"{FILES_PREFIX}data/prices.csv",
                        f"{FILES_PREFIX}assets/logo.png",
                        f"{FILES_PREFIX}scripts/run",
                    ]
                )
            ]
        )

        inventory = await client.list_text_files(SKILL_URL)

        # SKILL.md is served by read_skill itself; the binary and the
        # extension-less file are not text.
        assert inventory.files == ("references/eu-rules.md", "data/prices.csv")
        assert inventory.truncated is False

    @pytest.mark.asyncio
    async def test_skips_folders_and_hidden_entries(self):
        client, _ = _make_client(
            pages=[
                _page(
                    [
                        f"{FILES_PREFIX}references/",
                        f"{FILES_PREFIX}.dial-resource",
                        f"{FILES_PREFIX}.env",
                        f"{FILES_PREFIX}.hidden/secret.md",
                        f"{FILES_PREFIX}notes.md",
                    ]
                )
            ]
        )

        inventory = await client.list_text_files(SKILL_URL)

        assert inventory.files == ("notes.md",)

    @pytest.mark.asyncio
    async def test_percent_decodes_paths(self):
        client, _ = _make_client(pages=[_page([f"{FILES_PREFIX}references/api%20schema.md"])])

        inventory = await client.list_text_files(SKILL_URL)

        assert inventory.files == ("references/api schema.md",)

    @pytest.mark.asyncio
    async def test_ignores_entries_outside_the_listed_folder(self):
        client, _ = _make_client(
            pages=[_page(["skills/other-bucket/their-skill/files/leak.md", f"{FILES_PREFIX}ok.md"])]
        )

        inventory = await client.list_text_files(SKILL_URL)

        assert inventory.files == ("ok.md",)

    @pytest.mark.asyncio
    async def test_follows_pagination(self):
        client, dial = _make_client(
            pages=[
                _page([f"{FILES_PREFIX}a.md"], next_token="t1"),
                _page([f"{FILES_PREFIX}b.md"], next_token=None),
            ]
        )

        inventory = await client.list_text_files(SKILL_URL)

        assert inventory.files == ("a.md", "b.md")
        assert len(dial.list_calls) == 2

    @pytest.mark.asyncio
    async def test_stops_on_repeated_token(self):
        client, dial = _make_client(
            pages=[
                _page([f"{FILES_PREFIX}a.md"], next_token="stuck"),
                _page([f"{FILES_PREFIX}b.md"], next_token="stuck"),
            ]
        )

        inventory = await client.list_text_files(SKILL_URL)

        # A cursor that does not advance must not spend the page budget.
        assert inventory.files == ("a.md", "b.md")
        assert len(dial.list_calls) == 2

    @pytest.mark.asyncio
    async def test_page_budget_marks_truncated(self):
        settings = DialSkillsSettings(DIAL_SKILLS_LISTING_MAX_PAGES=2)
        client, dial = _make_client(
            pages=[
                _page([f"{FILES_PREFIX}a.md"], next_token="t1"),
                _page([f"{FILES_PREFIX}b.md"], next_token="t2"),
                _page([f"{FILES_PREFIX}c.md"], next_token="t3"),
            ],
            settings=settings,
        )

        inventory = await client.list_text_files(SKILL_URL)

        assert inventory.files == ("a.md", "b.md")
        assert inventory.truncated is True
        assert len(dial.list_calls) == 2

    @pytest.mark.asyncio
    async def test_max_files_marks_truncated(self):
        settings = DialSkillsSettings(DIAL_SKILLS_MAX_FILES=2)
        client, _ = _make_client(
            pages=[
                _page([f"{FILES_PREFIX}a.md", f"{FILES_PREFIX}b.md", f"{FILES_PREFIX}c.md"]),
            ],
            settings=settings,
        )

        inventory = await client.list_text_files(SKILL_URL)

        assert inventory.files == ("a.md", "b.md")
        assert inventory.truncated is True

    @pytest.mark.asyncio
    async def test_deduplicates_replayed_paths(self):
        client, _ = _make_client(
            pages=[
                _page([f"{FILES_PREFIX}a.md"], next_token="t1"),
                _page([f"{FILES_PREFIX}a.md", f"{FILES_PREFIX}b.md"], next_token=None),
            ]
        )

        inventory = await client.list_text_files(SKILL_URL)

        assert inventory.files == ("a.md", "b.md")


class TestReadTextFile:

    @pytest.mark.asyncio
    async def test_returns_decoded_text(self):
        client, _ = _make_client(content=b"# Rules\n")

        assert await client.read_text_file(SKILL_URL, "references/eu.md") == "# Rules\n"

    @pytest.mark.asyncio
    async def test_rejects_oversized_file(self):
        settings = DialSkillsSettings(DIAL_SKILLS_FILE_MAX_BYTES=4)
        client, _ = _make_client(content=b"too long", settings=settings)

        with pytest.raises(DialSkillFileTooLargeError, match="over the 4 byte limit"):
            await client.read_text_file(SKILL_URL, "big.md")

    @pytest.mark.asyncio
    async def test_rejects_non_utf8_file(self):
        client, _ = _make_client(content=b"\xff\xfe\x00binary")

        with pytest.raises(DialSkillFileNotTextError, match="not UTF-8 text"):
            await client.read_text_file(SKILL_URL, "weird.md")

    @pytest.mark.asyncio
    async def test_transport_error_always_carries_a_reason(self):
        client, dial = _make_client()
        # str(TimeoutError()) is empty, which would otherwise produce a
        # reason-less "Failed to read ...: " message.
        dial.read_error = TimeoutError()

        with pytest.raises(DialSkillFileReadError, match="TimeoutError"):
            await client.read_text_file(SKILL_URL, "slow.md")

    @pytest.mark.asyncio
    async def test_read_manifest_targets_skill_md(self):
        client, dial = _make_client(content=b"manifest")

        assert await client.read_manifest(SKILL_URL) == "manifest"
        assert dial.read_calls == [(SKILL_URL, "SKILL.md")]
