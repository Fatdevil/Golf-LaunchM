package com.antigravity.golf

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.fragment.app.Fragment
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

class CoachingFragment : Fragment() {

    private lateinit var swipeRefresh: SwipeRefreshLayout
    private lateinit var recyclerView: RecyclerView
    private lateinit var emptyView: LinearLayout
    private lateinit var errorView: LinearLayout
    private lateinit var errorText: TextView
    private lateinit var retryBtn: Button

    private lateinit var adapter: CoachingAdapter
    private var apiUrl: String = ""

    companion object {
        fun newInstance(url: String): CoachingFragment {
            val frag = CoachingFragment()
            val args = Bundle()
            args.putString("URL", url)
            frag.arguments = args
            return frag
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        apiUrl = arguments?.getString("URL") ?: ""
    }

    override fun onCreateView(
        inflater: LayoutInflater, container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View? {
        val root = inflater.inflate(R.layout.fragment_coaching, container, false)
        
        swipeRefresh = root.findViewById(R.id.swipeRefresh)
        recyclerView = root.findViewById(R.id.recyclerView)
        emptyView = root.findViewById(R.id.emptyView)
        errorView = root.findViewById(R.id.errorView)
        errorText = root.findViewById(R.id.errorText)
        retryBtn = root.findViewById(R.id.retryBtn)

        recyclerView.layoutManager = LinearLayoutManager(context)
        adapter = CoachingAdapter()
        recyclerView.adapter = adapter

        swipeRefresh.setOnRefreshListener {
            loadData()
        }

        retryBtn.setOnClickListener {
            loadData()
        }

        loadData()

        return root
    }

    private fun loadData() {
        if (apiUrl.isEmpty()) return
        
        errorView.visibility = View.GONE
        swipeRefresh.isRefreshing = true

        thread {
            try {
                val url = URL(apiUrl)
                val conn = url.openConnection() as HttpURLConnection
                conn.requestMethod = "GET"
                conn.connectTimeout = 5000
                conn.readTimeout = 5000

                if (conn.responseCode == 200) {
                    val stream = conn.inputStream
                    val response = stream.bufferedReader().use { it.readText() }
                    val jsonArray = JSONArray(response)
                    
                    val list = mutableListOf<JSONObject>()
                    for (i in 0 until jsonArray.length()) {
                        list.add(jsonArray.getJSONObject(i))
                    }

                    activity?.runOnUiThread {
                        swipeRefresh.isRefreshing = false
                        if (list.isEmpty()) {
                            recyclerView.visibility = View.GONE
                            emptyView.visibility = View.VISIBLE
                        } else {
                            emptyView.visibility = View.GONE
                            recyclerView.visibility = View.VISIBLE
                            adapter.setData(list)
                        }
                    }
                } else {
                    activity?.runOnUiThread { showError("Server error: ${conn.responseCode}") }
                }
            } catch (e: Exception) {
                activity?.runOnUiThread { showError("Connection failed") }
            }
        }
    }

    private fun showError(msg: String) {
        swipeRefresh.isRefreshing = false
        recyclerView.visibility = View.GONE
        emptyView.visibility = View.GONE
        errorView.visibility = View.VISIBLE
        errorText.text = msg
    }
}
