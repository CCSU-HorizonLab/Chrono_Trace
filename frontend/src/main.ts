import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import './styles/theme.css'
import './styles/base.css'
import './styles/panels.css'

const app = createApp(App)
app.use(router)
app.mount('#app')
