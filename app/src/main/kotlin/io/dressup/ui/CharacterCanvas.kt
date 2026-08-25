package io.dressup.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.gestures.detectDragGesturesAfterLongPress
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.IntOffset
import io.dressup.domain.PlacedItem

/** How wide a placed item draws, as a fraction of the canvas width. */
private const val ITEM_WIDTH_FRACTION = 0.28f

/**
 * The dressing surface: a base body with items laid over it.
 *
 * Coordinates crossing this boundary are always normalized 0..1 — the canvas
 * converts to pixels at the edge and nowhere else, so [io.dressup.domain.SnapCalculator]
 * and the ViewModel never need to know the screen size.
 *
 * Gestures:
 * - long-press then drag moves a placed item
 * - tap removes it
 *
 * Long-press rather than plain drag is deliberate: a 7-year-old resting a palm on
 * the tablet should not drag half the outfit off the character.
 */
@Composable
fun CharacterCanvas(
    baseImage: ImageBitmap,
    placed: List<PlacedItem>,
    imageFor: (PlacedItem) -> ImageBitmap?,
    onMove: (instanceId: Long, x: Float, y: Float, aspect: Float) -> Unit,
    onRemove: (instanceId: Long) -> Unit,
    modifier: Modifier = Modifier,
) {
    BoxWithConstraints(modifier = modifier) {
        val widthPx = with(LocalDensity.current) { maxWidth.toPx() }
        val heightPx = with(LocalDensity.current) { maxHeight.toPx() }
        val aspect = if (heightPx > 0f) widthPx / heightPx else 1f

        Image(
            bitmap = baseImage,
            contentDescription = null,
            modifier = Modifier.fillMaxSize(),
            contentScale = ContentScale.Fit,
        )

        // Drawn in list order, so the most recently touched item is on top.
        placed.forEach { item ->
            val bitmap = imageFor(item) ?: return@forEach
            PlacedItemLayer(
                item = item,
                bitmap = bitmap,
                canvasWidthPx = widthPx,
                canvasHeightPx = heightPx,
                aspect = aspect,
                onMove = onMove,
                onRemove = onRemove,
            )
        }
    }
}

@Composable
private fun PlacedItemLayer(
    item: PlacedItem,
    bitmap: ImageBitmap,
    canvasWidthPx: Float,
    canvasHeightPx: Float,
    aspect: Float,
    onMove: (Long, Float, Float, Float) -> Unit,
    onRemove: (Long) -> Unit,
) {
    val itemWidthPx = canvasWidthPx * ITEM_WIDTH_FRACTION
    val itemHeightPx = itemWidthPx * bitmap.height / bitmap.width.coerceAtLeast(1)

    // Local drag offset, so the item follows the finger every frame without a
    // state round-trip through the ViewModel. Committed on release.
    var dragPx by remember(item.instanceId) { mutableStateOf(Offset2(0f, 0f)) }

    val centreX = item.x * canvasWidthPx + dragPx.x
    val centreY = item.y * canvasHeightPx + dragPx.y

    Box(
        modifier = Modifier
            .offset {
                IntOffset(
                    x = (centreX - itemWidthPx / 2f).toInt(),
                    y = (centreY - itemHeightPx / 2f).toInt(),
                )
            }
            .pointerInput(item.instanceId) {
                detectTapGestures(onTap = { onRemove(item.instanceId) })
            }
            .pointerInput(item.instanceId, canvasWidthPx, canvasHeightPx) {
                detectDragGesturesAfterLongPress(
                    onDrag = { change, delta ->
                        change.consume()
                        dragPx = Offset2(dragPx.x + delta.x, dragPx.y + delta.y)
                    },
                    onDragEnd = {
                        val x = (item.x * canvasWidthPx + dragPx.x) / canvasWidthPx
                        val y = (item.y * canvasHeightPx + dragPx.y) / canvasHeightPx
                        dragPx = Offset2(0f, 0f)
                        onMove(item.instanceId, x.coerceIn(0f, 1f), y.coerceIn(0f, 1f), aspect)
                    },
                    onDragCancel = { dragPx = Offset2(0f, 0f) },
                )
            },
    ) {
        Image(
            bitmap = bitmap,
            contentDescription = item.item.id,
            modifier = Modifier.size(
                width = with(LocalDensity.current) { itemWidthPx.toDp() },
                height = with(LocalDensity.current) { itemHeightPx.toDp() },
            ),
            contentScale = ContentScale.Fit,
        )
    }
}

/** Minimal pair so this file does not depend on a geometry type for drag state. */
private data class Offset2(val x: Float, val y: Float)
