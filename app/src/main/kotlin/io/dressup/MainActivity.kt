package io.dressup

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.compose.viewModel
import io.dressup.data.CatalogRepository
import io.dressup.ui.DressUpScreen
import io.dressup.ui.DressUpViewModel

/**
 * Single-activity host. No DI framework: this app has exactly one dependency
 * edge (repository -> ViewModel), and a factory is less machinery than Hilt for
 * that. Revisit if a second screen ever needs its own graph.
 */
class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val repository = CatalogRepository(applicationContext)

        setContent {
            MaterialTheme {
                Surface {
                    val vm: DressUpViewModel = viewModel(factory = factoryFor(repository))
                    DressUpScreen(viewModel = vm, repository = repository)
                }
            }
        }
    }

    private fun factoryFor(repository: CatalogRepository) = object : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            DressUpViewModel(repository) as T
    }
}
