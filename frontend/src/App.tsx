import React from 'react'
import { Code, Zap, Download, FileText, Clock, CheckCircle, AlertCircle, Loader2, RefreshCw } from 'lucide-react'

interface File {
  name: string
  path: string
  size: number
  modified: string
}

interface Session {
  session_id: string
  prompt: string
  status: string
  current_node?: string
  files: string[]
  events: any[]
  created_at: string
  started_at?: string
  completed_at?: string
  error?: string
}

function App() {
  const [prompt, setPrompt] = React.useState('')
  const [session, setSession] = React.useState<Session | null>(null)
  const [files, setFiles] = React.useState<File[]>([])
  const [selectedFile, setSelectedFile] = React.useState<string | null>(null)
  const [fileContent, setFileContent] = React.useState('')
  const [isGenerating, setIsGenerating] = React.useState(false)
  const [ws, setWs] = React.useState<WebSocket | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [isLoadingFiles, setIsLoadingFiles] = React.useState(false)
  const [isLoadingContent, setIsLoadingContent] = React.useState(false)

  const startGeneration = async () => {
    if (!prompt.trim()) return

    setIsGenerating(true)
    setError(null)
    try {
      const response = await fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: prompt.trim() })
      })
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }
      
      const data = await response.json()
      setSession(data)
      
      // Connect to WebSocket
      const websocket = new WebSocket(`ws://localhost:8000/ws/progress/${data.session_id}`)
      websocket.onmessage = (event) => {
        const message = JSON.parse(event.data)
        console.log('WebSocket message:', message)
        
        if (message.type === 'session_data') {
          setSession(message.data)
        } else if (message.type === 'file') {
          // File was created, refresh file list
          fetchFiles(data.session_id)
        } else if (message.type === 'done') {
          setIsGenerating(false)
          fetchFiles(data.session_id)
        } else if (message.type === 'error') {
          setIsGenerating(false)
          setError(message.message)
          console.error('Generation error:', message.message)
        }
      }
      
      websocket.onopen = () => console.log('WebSocket connected')
      websocket.onclose = () => console.log('WebSocket disconnected')
      websocket.onerror = (error) => {
        console.error('WebSocket error:', error)
        setError('Connection error. Please try again.')
      }
      setWs(websocket)
      
    } catch (error) {
      console.error('Error starting generation:', error)
      setError(error instanceof Error ? error.message : 'Failed to start generation')
      setIsGenerating(false)
    }
  }

  const fetchFiles = async (sessionId: string) => {
    setIsLoadingFiles(true)
    try {
      const response = await fetch(`/api/files?session_id=${sessionId}`)
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }
      const data = await response.json()
      setFiles(data.files || [])
    } catch (error) {
      console.error('Error fetching files:', error)
      setError('Failed to load files')
    } finally {
      setIsLoadingFiles(false)
    }
  }

  const fetchFileContent = async (sessionId: string, filePath: string) => {
    setIsLoadingContent(true)
    try {
      const response = await fetch(`/api/file?session_id=${sessionId}&path=${filePath}`)
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }
      const data = await response.json()
      setFileContent(data.content)
      setSelectedFile(filePath)
    } catch (error) {
      console.error('Error fetching file content:', error)
      setError('Failed to load file content')
    } finally {
      setIsLoadingContent(false)
    }
  }

  const downloadZip = async (sessionId: string) => {
    try {
      const response = await fetch(`/api/zip?session_id=${sessionId}`)
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }
      const blob = await response.blob()
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `project_${sessionId.slice(0, 8)}.zip`
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)
    } catch (error) {
      console.error('Error downloading ZIP:', error)
      setError('Failed to download project')
    }
  }

  const retryGeneration = () => {
    setError(null)
    if (session) {
      startGeneration()
    }
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="w-5 h-5 text-green-500" />
      case 'error':
        return <AlertCircle className="w-5 h-5 text-red-500" />
      case 'running':
        return <Loader2 className="w-5 h-5 text-blue-500 animate-spin" />
      default:
        return <Clock className="w-5 h-5 text-gray-500" />
    }
  }

  const getCurrentNode = (session: Session) => {
    if (session.current_node) {
      return session.current_node.charAt(0).toUpperCase() + session.current_node.slice(1)
    }
    return 'Starting...'
  }

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
  }

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* Header */}
      <header className="bg-white shadow-sm border-b">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <div className="flex items-center">
              <Code className="w-8 h-8 text-primary-600" />
              <h1 className="ml-2 text-xl font-bold text-gray-900">Code Builder</h1>
            </div>
            <div className="text-sm text-gray-500">
              AI-Powered Project Generator
            </div>
          </div>
        </div>
      </header>

      {/* Error Banner */}
      {error && (
        <div className="bg-red-50 border-l-4 border-red-400 p-4">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="flex items-center justify-between">
              <div className="flex items-center">
                <AlertCircle className="w-5 h-5 text-red-400 mr-2" />
                <p className="text-sm text-red-700">{error}</p>
              </div>
              <button
                onClick={() => setError(null)}
                className="text-red-400 hover:text-red-600"
              >
                <RefreshCw className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="flex-1">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
            {/* Left Column - Input & Status */}
            <div className="lg:col-span-1 space-y-6">
              {/* Project Input */}
              <div className="bg-white rounded-lg shadow-sm border p-6">
                <h2 className="text-lg font-semibold text-gray-900 mb-4">Create New Project</h2>
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Describe your project
                    </label>
                    <textarea
                      value={prompt}
                      onChange={(e) => setPrompt(e.target.value)}
                      placeholder="e.g., Create a simple calculator app with user authentication"
                      className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                      rows={4}
                      disabled={isGenerating}
                    />
                  </div>
                  <button
                    onClick={startGeneration}
                    disabled={!prompt.trim() || isGenerating}
                    className="w-full bg-primary-600 text-white px-4 py-2 rounded-md hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center"
                  >
                    {isGenerating ? (
                      <>
                        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                        Generating...
                      </>
                    ) : (
                      <>
                        <Zap className="w-4 h-4 mr-2" />
                        Generate Project
                      </>
                    )}
                  </button>
                </div>
              </div>

              {/* Status */}
              {session && (
                <div className="bg-white rounded-lg shadow-sm border p-6">
                  <h3 className="text-lg font-semibold text-gray-900 mb-4">Generation Status</h3>
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-gray-600">Status:</span>
                      <div className="flex items-center">
                        {getStatusIcon(session.status)}
                        <span className="ml-2 text-sm font-medium capitalize">{session.status}</span>
                      </div>
                    </div>
                    {session.current_node && (
                      <div className="flex items-center justify-between">
                        <span className="text-sm text-gray-600">Current Step:</span>
                        <span className="text-sm font-medium">{getCurrentNode(session)}</span>
                      </div>
                    )}
                    {session.files.length > 0 && (
                      <div className="flex items-center justify-between">
                        <span className="text-sm text-gray-600">Files Created:</span>
                        <span className="text-sm font-medium">{session.files.length}</span>
                      </div>
                    )}
                    {session.status === 'completed' && (
                      <button
                        onClick={() => downloadZip(session.session_id)}
                        className="w-full bg-green-600 text-white px-4 py-2 rounded-md hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-green-500 flex items-center justify-center"
                      >
                        <Download className="w-4 h-4 mr-2" />
                        Download ZIP
                      </button>
                    )}
                    {session.status === 'error' && (
                      <button
                        onClick={retryGeneration}
                        className="w-full bg-red-600 text-white px-4 py-2 rounded-md hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 flex items-center justify-center"
                      >
                        <RefreshCw className="w-4 h-4 mr-2" />
                        Retry Generation
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* Right Column - Files & Content */}
            <div className="lg:col-span-2 space-y-6">
              {/* Files List */}
              {files.length > 0 && (
                <div className="bg-white rounded-lg shadow-sm border">
                  <div className="px-6 py-4 border-b">
                    <h3 className="text-lg font-semibold text-gray-900 flex items-center">
                      <FileText className="w-5 h-5 mr-2" />
                      Generated Files
                      {isLoadingFiles && <Loader2 className="w-4 h-4 ml-2 animate-spin text-gray-400" />}
                    </h3>
                  </div>
                  <div className="divide-y">
                    {files.map((file) => (
                      <div
                        key={file.path}
                        className={`px-6 py-3 cursor-pointer hover:bg-gray-50 ${
                          selectedFile === file.path ? 'bg-primary-50 border-r-4 border-primary-500' : ''
                        }`}
                        onClick={() => fetchFileContent(session!.session_id, file.path)}
                      >
                        <div className="flex items-center justify-between">
                          <div>
                            <div className="text-sm font-medium text-gray-900">{file.name}</div>
                            <div className="text-xs text-gray-500">
                              {formatFileSize(file.size)}
                            </div>
                          </div>
                          <div className="text-xs text-gray-400">
                            {new Date(file.modified).toLocaleTimeString()}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* File Content */}
              {selectedFile && (
                <div className="bg-white rounded-lg shadow-sm border">
                  <div className="px-6 py-4 border-b">
                    <h3 className="text-lg font-semibold text-gray-900 flex items-center">
                      {selectedFile}
                      {isLoadingContent && <Loader2 className="w-4 h-4 ml-2 animate-spin text-gray-400" />}
                    </h3>
                  </div>
                  <div className="p-6">
                    {isLoadingContent ? (
                      <div className="flex items-center justify-center py-8">
                        <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
                        <span className="ml-2 text-gray-500">Loading file content...</span>
                      </div>
                    ) : (
                      <pre className="bg-gray-900 text-gray-100 p-4 rounded-md overflow-auto text-sm">
                        <code>{fileContent}</code>
                      </pre>
                    )}
                  </div>
                </div>
              )}

              {/* Empty State */}
              {!session && !isGenerating && (
                <div className="bg-white rounded-lg shadow-sm border p-12 text-center">
                  <Code className="w-12 h-12 text-gray-400 mx-auto mb-4" />
                  <h3 className="text-lg font-medium text-gray-900 mb-2">Ready to Generate</h3>
                  <p className="text-gray-500">Enter a project description and click "Generate Project" to get started.</p>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Footer */}
      <footer className="bg-white border-t">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex flex-col md:flex-row justify-between items-center">
            <div className="flex items-center mb-4 md:mb-0">
              <Code className="w-5 h-5 text-primary-600 mr-2" />
              <span className="text-sm text-gray-600">Code Builder - AI-Powered Project Generator</span>
            </div>
            <div className="flex items-center space-x-6 text-sm text-gray-500">
              <span>Built with React + FastAPI + LangGraph</span>
              <span>•</span>
              <span>Powered by Groq AI</span>
            </div>
          </div>
        </div>
      </footer>
    </div>
  )
}

export default App
