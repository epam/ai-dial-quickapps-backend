from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_client import DialException, InvalidDialURLError, ResourceNotFoundError

from quickapp.dial_skills._dial_skill import _DialSkill
from quickapp.dial_skills._dial_skills_client import DialSkillsClient
from quickapp.dial_skills._exceptions import SkillAccessDenied, SkillClientError, SkillNotFound
from quickapp.skills._exceptions import SkillFileNotText, SkillFileTooLarge
from quickapp.skills._settings import SkillsSettings
from quickapp.skills._skill import SkillFileContent, SkillFileEntry
from quickapp.skills._skill_metadata import SkillMetadata

SKILL_URL = "skills/bucket/support/refunds"
LISTING_URL = f"{SKILL_URL}/files/"


def _page(paths: list[str], next_token: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        url=LISTING_URL,
        next_token=next_token,
        items=[SimpleNamespace(url=f"{LISTING_URL}{p}") for p in paths],
    )


def _client(
    settings: SkillsSettings | None = None,
    get_file: AsyncMock | None = None,
    list_files: AsyncMock | None = None,
) -> tuple[DialSkillsClient, MagicMock]:
    dial_client = MagicMock()
    dial_client.skills = MagicMock()
    dial_client.skills.get_file = get_file or AsyncMock()
    dial_client.skills.list_files = list_files or AsyncMock(return_value=_page([]))
    return DialSkillsClient(dial_client, settings or SkillsSettings()), dial_client


def _download(payload: bytes) -> AsyncMock:
    response = MagicMock()
    response.aget_content = AsyncMock(return_value=payload)
    return AsyncMock(return_value=response)


class TestGetFile:
    @pytest.mark.asyncio
    async def test_returns_decoded_text_with_a_guessed_content_type(self):
        client, _ = _client(get_file=_download(b"# Matrix"))

        content = await client.get_file(SKILL_URL, "references/matrix.md")

        assert content.text == "# Matrix"
        assert content.path == "references/matrix.md"
        assert content.content_type == "text/markdown"

    @pytest.mark.asyncio
    async def test_manifest_read_is_one_round_trip_for_skill_md(self):
        get_file = _download(b"---\nname: s\ndescription: d\n---\n")
        client, _ = _client(get_file=get_file)

        await client.get_manifest(SKILL_URL)

        get_file.assert_awaited_once_with(SKILL_URL, "SKILL.md")

    @pytest.mark.asyncio
    async def test_oversized_file_is_refused(self):
        client, _ = _client(SkillsSettings(file_max_bytes=4), get_file=_download(b"too long"))

        with pytest.raises(SkillFileTooLarge):
            await client.get_file(SKILL_URL, "a.md")

    @pytest.mark.asyncio
    async def test_binary_file_is_refused(self):
        client, _ = _client(get_file=_download(b"\x89PNG\xff\xfe"))

        with pytest.raises(SkillFileNotText):
            await client.get_file(SKILL_URL, "logo.png")


class TestErrorMapping:
    """Library exceptions, never raw HTTP statuses."""

    @pytest.mark.asyncio
    async def test_not_found_maps_to_skill_not_found(self):
        client, _ = _client(get_file=AsyncMock(side_effect=ResourceNotFoundError("missing")))

        with pytest.raises(SkillNotFound, match="was not found"):
            await client.get_file(SKILL_URL, "a.md")

    @pytest.mark.asyncio
    async def test_forbidden_maps_to_access_denied(self):
        client, _ = _client(get_file=AsyncMock(side_effect=DialException("nope", status_code=403)))

        with pytest.raises(SkillAccessDenied, match="not be shared"):
            await client.get_file(SKILL_URL, "a.md")

    @pytest.mark.asyncio
    async def test_other_dial_errors_map_to_a_generic_client_error(self):
        client, _ = _client(get_file=AsyncMock(side_effect=DialException("boom", status_code=500)))

        with pytest.raises(SkillClientError, match="boom"):
            await client.get_file(SKILL_URL, "a.md")

    @pytest.mark.asyncio
    async def test_unexpected_errors_still_become_client_errors(self):
        client, _ = _client(get_file=AsyncMock(side_effect=RuntimeError("socket died")))

        with pytest.raises(SkillClientError, match="socket died"):
            await client.get_file(SKILL_URL, "a.md")

    @pytest.mark.asyncio
    async def test_error_text_carries_a_sanitized_url(self):
        client, _ = _client(get_file=AsyncMock(side_effect=ResourceNotFoundError("missing")))

        with pytest.raises(SkillNotFound) as excinfo:
            await client.get_file(f"{SKILL_URL}?token=secret", "a.md")

        assert "secret" not in str(excinfo.value)


class TestListFiles:
    @pytest.mark.asyncio
    async def test_derives_paths_relative_to_the_skill_root(self):
        client, _ = _client(
            list_files=AsyncMock(return_value=_page(["references/matrix.md", "scripts/run.py"]))
        )

        entries, truncated = await client.list_files(SKILL_URL)

        assert [e.path for e in entries] == ["references/matrix.md", "scripts/run.py"]
        assert truncated is False

    @pytest.mark.asyncio
    async def test_percent_encoded_segments_are_decoded(self):
        client, _ = _client(list_files=AsyncMock(return_value=_page(["refs/my%20file.md"])))

        entries, _ = await client.list_files(SKILL_URL)

        # The library encodes what it is given, so a still-encoded path here
        # would reach Core double-encoded.
        assert [e.path for e in entries] == ["refs/my file.md"]

    @pytest.mark.asyncio
    async def test_the_manifest_is_not_listed_as_a_bundled_file(self):
        client, _ = _client(list_files=AsyncMock(return_value=_page(["SKILL.md", "a.md"])))

        entries, _ = await client.list_files(SKILL_URL)

        assert [e.path for e in entries] == ["a.md"]

    @pytest.mark.asyncio
    async def test_folder_nodes_are_filtered_out(self):
        client, _ = _client(list_files=AsyncMock(return_value=_page(["references/", "a.md"])))

        entries, _ = await client.list_files(SKILL_URL)

        assert [e.path for e in entries] == ["a.md"]

    @pytest.mark.asyncio
    async def test_follows_next_token_to_exhaustion(self):
        list_files = AsyncMock(
            side_effect=[_page(["a.md"], next_token="t1"), _page(["b.md"], next_token=None)]
        )
        client, _ = _client(list_files=list_files)

        entries, truncated = await client.list_files(SKILL_URL)

        # A page may hold fewer nodes than `limit`, so a single call would
        # silently return a short inventory.
        assert [e.path for e in entries] == ["a.md", "b.md"]
        assert truncated is False
        assert list_files.await_count == 2

    @pytest.mark.asyncio
    async def test_cap_stops_the_walk_and_marks_the_inventory_truncated(self):
        list_files = AsyncMock(return_value=_page(["a.md", "b.md", "c.md"], next_token="t1"))
        client, _ = _client(SkillsSettings(inventory_max_entries=2), list_files=list_files)

        entries, truncated = await client.list_files(SKILL_URL)

        assert [e.path for e in entries] == ["a.md", "b.md"]
        assert truncated is True
        assert list_files.await_count == 1

    @pytest.mark.asyncio
    async def test_exactly_at_the_cap_is_not_truncated(self):
        client, _ = _client(
            SkillsSettings(inventory_max_entries=2),
            list_files=AsyncMock(return_value=_page(["a.md", "b.md"])),
        )

        entries, truncated = await client.list_files(SKILL_URL)

        assert len(entries) == 2
        assert truncated is False

    @pytest.mark.asyncio
    async def test_listing_is_recursive_and_bounded_by_cores_page_limit(self):
        list_files = AsyncMock(return_value=_page([]))
        client, _ = _client(SkillsSettings(inventory_max_entries=5000), list_files=list_files)

        await client.list_files(SKILL_URL)

        kwargs = list_files.await_args.kwargs
        assert kwargs["recursive"] is True
        assert kwargs["limit"] == 1000


class TestDialSkillCaching:
    """Within a request the skill caches every file it has read; nothing is
    cached across requests, since Core exposes no cheap aggregate etag yet."""

    @pytest.mark.asyncio
    async def test_a_file_read_twice_costs_one_round_trip(self):
        client = MagicMock(spec=DialSkillsClient)
        client.get_file = AsyncMock(
            return_value=SkillFileContent(path="a.md", text="x", content_type="text/markdown")
        )
        skill = _DialSkill(
            metadata=SkillMetadata(name="s", description="d"),
            manifest="manifest",
            files=[],
            url=SKILL_URL,
            config_index=0,
            client=client,
        )

        assert (await skill.read_file("a.md")).text == "x"
        assert (await skill.read_file("a.md")).text == "x"
        client.get_file.assert_awaited_once_with(SKILL_URL, "a.md")

    @pytest.mark.asyncio
    async def test_manifest_and_inventory_need_no_io(self):
        client = MagicMock(spec=DialSkillsClient)
        skill = _DialSkill(
            metadata=SkillMetadata(name="s", description="d"),
            manifest="manifest",
            files=[SkillFileEntry(path="a.md")],
            url=SKILL_URL,
            config_index=0,
            client=client,
            files_truncated=True,
        )

        assert skill.read_manifest() == "manifest"
        assert [e.path for e in skill.list_files()] == ["a.md"]
        assert skill.inventory_truncated is True
        client.get_file.assert_not_called()


class TestListingRobustness:
    """The pagination loop is driven by a server-supplied cursor and nothing
    above it imposes a deadline, so it has to defend itself."""

    @pytest.mark.asyncio
    async def test_a_repeated_page_token_stops_the_walk(self):
        # The next request would be byte-identical, so following it forever
        # would hang the whole chat request inside initialization.
        list_files = AsyncMock(return_value=_page(["a.md"], next_token="stuck"))
        client, _ = _client(list_files=list_files)

        entries, truncated = await client.list_files(SKILL_URL)

        assert [e.path for e in entries] == ["a.md"]
        assert truncated is True
        assert list_files.await_count == 2

    @pytest.mark.asyncio
    async def test_an_endless_cursor_chain_is_capped(self):
        counter = iter(range(10_000))
        list_files = AsyncMock(
            side_effect=lambda *a, **k: _page([], next_token=f"t{next(counter)}")
        )
        client, _ = _client(list_files=list_files)

        entries, truncated = await client.list_files(SKILL_URL)

        assert entries == []
        assert truncated is True
        assert list_files.await_count == 50

    @pytest.mark.asyncio
    async def test_an_item_url_outside_the_listing_is_dropped(self):
        # `removeprefix` is a silent no-op on a mismatch, which would advertise a
        # full `skills/<bucket>/...` URL as a path inside the skill.
        page = SimpleNamespace(
            url=LISTING_URL,
            next_token=None,
            items=[SimpleNamespace(url="skills/other-bucket/elsewhere/files/a.md")],
        )
        client, _ = _client(list_files=AsyncMock(return_value=page))

        entries, _ = await client.list_files(SKILL_URL)

        assert entries == []


class TestErrorDetail:
    @pytest.mark.asyncio
    async def test_a_timeout_still_names_a_cause(self):
        # `str(TimeoutError())` is empty, which rendered as "... from DIAL: ".
        client, _ = _client(get_file=AsyncMock(side_effect=TimeoutError()))

        with pytest.raises(SkillClientError, match="TimeoutError"):
            await client.get_file(SKILL_URL, "a.md")

    @pytest.mark.asyncio
    async def test_an_unusable_path_keeps_the_self_correction_hint(self):
        # Must be SkillFileNotFound, not SkillClientError: only that branch of
        # the reader tool lists what the skill does contain.
        client, _ = _client(get_file=AsyncMock(side_effect=InvalidDialURLError("bad path")))

        with pytest.raises(SkillNotFound):
            await client.get_file(SKILL_URL, "refs%2Fa.md")
