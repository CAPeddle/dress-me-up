package io.dressup.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import io.dressup.data.CatalogRepository
import io.dressup.domain.CatalogItem
import io.dressup.domain.Character
import io.dressup.domain.PlacedItem
import io.dressup.domain.SnapCalculator
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

sealed interface DressUpUiState {
    data object Loading : DressUpUiState

    data class Ready(
        val character: Character,
        val characters: List<Character>,
        val catalog: List<CatalogItem>,
        val placed: List<PlacedItem> = emptyList(),
        val selectedCategory: String? = null,
        val selectedGroup: String? = null,
    ) : DressUpUiState {

        /** The tray contents: catalog filtered by whatever the player has picked. */
        val visibleItems: List<CatalogItem>
            get() = catalog.filter { item ->
                (selectedCategory == null || item.category == selectedCategory) &&
                    (selectedGroup == null || item.group == selectedGroup)
            }

        val categories: List<String> get() = catalog.map { it.category }.distinct().sorted()
        val groups: List<String> get() = catalog.map { it.group }.distinct().sorted()
    }

    data class Failed(val message: String) : DressUpUiState
}

sealed interface DressUpEvent {
    data class DropItem(val item: CatalogItem, val x: Float, val y: Float, val aspect: Float) : DressUpEvent
    data class MovePlaced(val instanceId: Long, val x: Float, val y: Float, val aspect: Float) : DressUpEvent
    data class RemovePlaced(val instanceId: Long) : DressUpEvent
    data class SelectCharacter(val characterId: String) : DressUpEvent
    data class FilterCategory(val category: String?) : DressUpEvent
    data class FilterGroup(val group: String?) : DressUpEvent
    data object ClearAll : DressUpEvent
}

class DressUpViewModel(private val repository: CatalogRepository) : ViewModel() {

    private val _uiState = MutableStateFlow<DressUpUiState>(DressUpUiState.Loading)
    val uiState: StateFlow<DressUpUiState> = _uiState.asStateFlow()

    /** Monotonic so the same catalog item can be placed more than once. */
    private var nextInstanceId = 1L

    init {
        load()
    }

    private fun load() = viewModelScope.launch {
        _uiState.value = try {
            val characters = repository.loadCharacters()
            DressUpUiState.Ready(
                character = characters.first(),
                characters = characters,
                catalog = repository.loadCatalog(),
            )
        } catch (e: Exception) {
            DressUpUiState.Failed(e.message ?: "could not load the catalog")
        }
    }

    fun onEvent(event: DressUpEvent) = _uiState.update { state ->
        if (state !is DressUpUiState.Ready) return@update state
        when (event) {
            is DressUpEvent.DropItem -> state.withDroppedItem(event)
            is DressUpEvent.MovePlaced -> state.withMovedItem(event)
            is DressUpEvent.RemovePlaced ->
                state.copy(placed = state.placed.filterNot { it.instanceId == event.instanceId })

            is DressUpEvent.SelectCharacter ->
                state.characters.find { it.id == event.characterId }
                    // Switching character drops the outfit: snap points differ per
                    // body, so carrying placements across would misplace them.
                    ?.let { state.copy(character = it, placed = emptyList()) }
                    ?: state

            is DressUpEvent.FilterCategory -> state.copy(selectedCategory = event.category)
            is DressUpEvent.FilterGroup -> state.copy(selectedGroup = event.group)
            DressUpEvent.ClearAll -> state.copy(placed = emptyList())
        }
    }

    private fun DressUpUiState.Ready.withDroppedItem(event: DressUpEvent.DropItem): DressUpUiState.Ready {
        val placement = SnapCalculator.resolve(
            dropX = event.x,
            dropY = event.y,
            category = event.item.category,
            snapPoints = character.snapPoints,
            aspect = event.aspect,
        )
        val placedItem = PlacedItem(
            instanceId = nextInstanceId++,
            item = event.item,
            x = placement.x,
            y = placement.y,
            snappedTo = placement.snappedTo,
        )
        // One item per occupied snap point — a second hat replaces the first
        // rather than stacking invisibly on top of it.
        val cleared =
            if (placement.snappedTo == null) placed
            else placed.filterNot { it.snappedTo == placement.snappedTo }
        return copy(placed = cleared + placedItem)
    }

    private fun DressUpUiState.Ready.withMovedItem(event: DressUpEvent.MovePlaced): DressUpUiState.Ready {
        val moving = placed.find { it.instanceId == event.instanceId } ?: return this
        val placement = SnapCalculator.resolve(
            dropX = event.x,
            dropY = event.y,
            category = moving.item.category,
            snapPoints = character.snapPoints,
            aspect = event.aspect,
        )
        val updated = moving.copy(x = placement.x, y = placement.y, snappedTo = placement.snappedTo)
        // Re-append so the item the player just touched draws on top.
        val others = placed.filterNot {
            it.instanceId == moving.instanceId ||
                (placement.snappedTo != null && it.snappedTo == placement.snappedTo)
        }
        return copy(placed = others + updated)
    }
}
