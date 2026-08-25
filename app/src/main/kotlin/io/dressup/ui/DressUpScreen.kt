package io.dressup.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.dressup.data.CatalogRepository
import io.dressup.domain.CatalogItem

/**
 * How many tray items to decode ahead of the player tapping one.
 *
 * Decoding the whole catalog would be roughly a megabyte per 512px item — well
 * past what a 4 GB tablet will give a single app. Bounded preloading keeps the
 * tray responsive without that risk. Proper windowed loading tied to LazyRow
 * scroll position is Phase 3 work.
 */
private const val TRAY_PRELOAD = 48

/**
 * The whole game, one screen: character on the left, item tray on the right.
 *
 * Landscape-only by manifest — this is a tablet dress-up game, and portrait would
 * leave the character too small for a 7-year-old to aim at.
 */
@Composable
fun DressUpScreen(
    viewModel: DressUpViewModel,
    repository: CatalogRepository,
    modifier: Modifier = Modifier,
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()

    when (val current = state) {
        DressUpUiState.Loading -> Centered { CircularProgressIndicator() }

        is DressUpUiState.Failed -> Centered { Text("Could not start: ${current.message}") }

        is DressUpUiState.Ready -> {
            val visible = current.visibleItems
            // One decode pass for everything on screen. Keyed so it only re-runs
            // when the set of needed images actually changes, not every frame.
            val wanted = remember(current.character, current.placed, visible) {
                buildList {
                    add(current.character.baseImage)
                    current.placed.forEach { add(it.item.image) }
                    visible.take(TRAY_PRELOAD).forEach { add(it.image) }
                }.distinct()
            }
            val images = rememberImages(repository, wanted)

            Row(modifier = modifier.fillMaxSize()) {
                CharacterPane(
                    state = current,
                    images = images,
                    onEvent = viewModel::onEvent,
                    modifier = Modifier.weight(2f).fillMaxSize(),
                )
                TrayPane(
                    state = current,
                    visible = visible,
                    images = images,
                    onEvent = viewModel::onEvent,
                    modifier = Modifier.weight(1f).fillMaxSize().padding(8.dp),
                )
            }
        }
    }
}

@Composable
private fun CharacterPane(
    state: DressUpUiState.Ready,
    images: Map<String, ImageBitmap>,
    onEvent: (DressUpEvent) -> Unit,
    modifier: Modifier = Modifier,
) {
    Box(modifier = modifier) {
        images[state.character.baseImage]?.let { base ->
            CharacterCanvas(
                baseImage = base,
                placed = state.placed,
                imageFor = { images[it.item.image] },
                onMove = { id, x, y, aspect -> onEvent(DressUpEvent.MovePlaced(id, x, y, aspect)) },
                onRemove = { id -> onEvent(DressUpEvent.RemovePlaced(id)) },
                modifier = Modifier.fillMaxSize(),
            )
        }
        Button(
            onClick = { onEvent(DressUpEvent.ClearAll) },
            modifier = Modifier.align(Alignment.BottomStart).padding(16.dp),
        ) {
            Text("Start again")
        }
    }
}

@Composable
private fun TrayPane(
    state: DressUpUiState.Ready,
    visible: List<CatalogItem>,
    images: Map<String, ImageBitmap>,
    onEvent: (DressUpEvent) -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(8.dp)) {
        FilterRow(state.categories, state.selectedCategory) { onEvent(DressUpEvent.FilterCategory(it)) }
        FilterRow(state.groups, state.selectedGroup) { onEvent(DressUpEvent.FilterGroup(it)) }

        if (visible.isEmpty()) {
            Text("No items yet — run tools/build_catalog.py")
            return@Column
        }

        LazyRow(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            modifier = Modifier.fillMaxWidth(),
        ) {
            items(visible, key = { it.id }) { item ->
                TrayItem(
                    item = item,
                    bitmap = images[item.image],
                    // Tapping the tray drops the item at the character's centre;
                    // the player then long-press-drags it into place.
                    onPick = { onEvent(DressUpEvent.DropItem(item, x = 0.5f, y = 0.5f, aspect = 1f)) },
                )
            }
        }
    }
}

@Composable
private fun TrayItem(item: CatalogItem, bitmap: ImageBitmap?, onPick: () -> Unit) {
    Box(
        modifier = Modifier
            .size(96.dp) // comfortably past the 56dp minimum touch target
            .clickable(onClick = onPick),
        contentAlignment = Alignment.Center,
    ) {
        bitmap?.let {
            Image(bitmap = it, contentDescription = item.id, modifier = Modifier.fillMaxSize())
        }
    }
}

@Composable
private fun FilterRow(values: List<String>, selected: String?, onSelect: (String?) -> Unit) {
    LazyRow(
        horizontalArrangement = Arrangement.spacedBy(4.dp),
        modifier = Modifier.fillMaxWidth().height(48.dp),
    ) {
        items(values, key = { it }) { value ->
            FilterChip(
                selected = selected == value,
                // Tapping the active chip clears the filter — no separate "all" chip.
                onClick = { onSelect(if (selected == value) null else value) },
                label = { Text(value) },
            )
        }
    }
}

/** Decode a set of asset images off the main thread, recomposing as they arrive. */
@Composable
private fun rememberImages(
    repository: CatalogRepository,
    paths: List<String>,
): Map<String, ImageBitmap> {
    val state = produceState(initialValue = emptyMap<String, ImageBitmap>(), paths) {
        val decoded = mutableMapOf<String, ImageBitmap>()
        paths.forEach { path ->
            runCatching { repository.image(path) }.getOrNull()?.let { decoded[path] = it }
        }
        value = decoded.toMap()
    }
    return state.value
}

@Composable
private fun Centered(content: @Composable () -> Unit) {
    Box(
        modifier = Modifier.fillMaxSize().background(Color.White),
        contentAlignment = Alignment.Center,
    ) { content() }
}
