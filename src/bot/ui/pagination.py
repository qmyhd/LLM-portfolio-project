"""
Pagination Base View

Provides reusable pagination for any list-based data.
"""

from typing import Any, Callable, List, Optional

import discord


class PaginatedView(discord.ui.View):
    """Base class for paginated views with navigation buttons."""

    def __init__(
        self,
        items: List[Any],
        page_size: int = 10,
        timeout: float = 120.0,
    ):
        """Initialize paginated view.

        Args:
            items: List of items to paginate
            page_size: Items per page
            timeout: View timeout in seconds
        """
        super().__init__(timeout=timeout)
        self.items = items
        self.page_size = page_size
        self.current_page = 0
        self._update_button_states()

    @property
    def total_pages(self) -> int:
        """Total number of pages."""
        if not self.items:
            return 1
        return max(1, (len(self.items) + self.page_size - 1) // self.page_size)

    @property
    def current_items(self) -> List[Any]:
        """Get items for current page."""
        start = self.current_page * self.page_size
        end = start + self.page_size
        return self.items[start:end]

    def _update_button_states(self):
        """Update button enabled/disabled states."""
        # Find buttons by custom_id
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if child.custom_id == "first":
                    child.disabled = self.current_page == 0
                elif child.custom_id == "prev":
                    child.disabled = self.current_page == 0
                elif child.custom_id == "next":
                    child.disabled = self.current_page >= self.total_pages - 1
                elif child.custom_id == "last":
                    child.disabled = self.current_page >= self.total_pages - 1

    def build_embed(self) -> discord.Embed:
        """Build embed for current page. Override in subclass."""
        raise NotImplementedError("Subclass must implement build_embed()")

    async def update_message(self, interaction: discord.Interaction):
        """Update the message with new embed and view state."""
        self._update_button_states()
        await interaction.response.edit_message(
            embed=self.build_embed(),
            view=self,
        )

    @discord.ui.button(
        label="⏮️",
        style=discord.ButtonStyle.secondary,
        custom_id="first",
        row=0,
    )
    async def first_page(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Go to first page."""
        self.current_page = 0
        await self.update_message(interaction)

    @discord.ui.button(
        label="◀️",
        style=discord.ButtonStyle.secondary,
        custom_id="prev",
        row=0,
    )
    async def prev_page(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Go to previous page."""
        if self.current_page > 0:
            self.current_page -= 1
        await self.update_message(interaction)

    @discord.ui.button(
        label="▶️",
        style=discord.ButtonStyle.secondary,
        custom_id="next",
        row=0,
    )
    async def next_page(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Go to next page."""
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
        await self.update_message(interaction)

    @discord.ui.button(
        label="⏭️",
        style=discord.ButtonStyle.secondary,
        custom_id="last",
        row=0,
    )
    async def last_page(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Go to last page."""
        self.current_page = self.total_pages - 1
        await self.update_message(interaction)

    async def on_timeout(self):
        """Disable buttons on timeout."""
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
