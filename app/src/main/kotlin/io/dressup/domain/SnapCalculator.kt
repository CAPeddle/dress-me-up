package io.dressup.domain

import kotlin.math.hypot

/**
 * Decides where a dropped item lands: locked onto a snap point, or free-placed.
 *
 * Pure and canvas-agnostic so it can be tested without a device — which matters
 * here, because there is no emulator and device sessions are expensive.
 */
object SnapCalculator {

    /**
     * How close a drop must be to snap, as a fraction of the canvas's *shorter*
     * edge. Using one edge rather than each axis keeps the pull circular on
     * screen instead of an ellipse stretched by the canvas aspect ratio.
     */
    const val DEFAULT_SNAP_RADIUS: Float = 0.12f

    /**
     * @param aspect canvas width / height, used to convert normalized distance
     *   into something proportional to what the player actually sees. A drop
     *   0.1 to the left of a point on a wide canvas is further away in real
     *   pixels than 0.1 above it.
     */
    fun resolve(
        dropX: Float,
        dropY: Float,
        category: String,
        snapPoints: List<SnapPoint>,
        radius: Float = DEFAULT_SNAP_RADIUS,
        aspect: Float = 1f,
    ): Placement {
        require(radius >= 0f) { "radius must not be negative, was $radius" }
        require(aspect > 0f) { "aspect must be positive, was $aspect" }

        val nearest = snapPoints
            .filter { it.category == category }
            .minByOrNull { distance(dropX, dropY, it, aspect) }
            ?: return Placement.free(dropX, dropY)

        return if (distance(dropX, dropY, nearest, aspect) <= radius) {
            Placement(x = nearest.x, y = nearest.y, snappedTo = nearest.id)
        } else {
            Placement.free(dropX, dropY)
        }
    }

    /**
     * Distance in units of the shorter canvas edge. The longer axis is scaled up
     * so both axes contribute in proportion to on-screen distance.
     */
    private fun distance(x: Float, y: Float, point: SnapPoint, aspect: Float): Float {
        val dx = (x - point.x) * if (aspect >= 1f) aspect else 1f
        val dy = (y - point.y) * if (aspect >= 1f) 1f else 1f / aspect
        return hypot(dx, dy)
    }
}

/** Where an item ended up, and whether it locked onto a snap point. */
data class Placement(
    val x: Float,
    val y: Float,
    val snappedTo: String?,
) {
    val isSnapped: Boolean get() = snappedTo != null

    companion object {
        fun free(x: Float, y: Float) = Placement(x = x, y = y, snappedTo = null)
    }
}
