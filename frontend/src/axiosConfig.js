import axios from 'axios';

axios.defaults.baseURL = 'http://localhost:8000';

const storedToken = localStorage.getItem('token');
if (storedToken) {
	axios.defaults.headers.common['Authorization'] = `Bearer ${storedToken}`;
}

axios.interceptors.response.use(
	(response) => response,
	(error) => {
		if (error.response?.status === 401 && window.location.pathname !== '/login') {
			window.dispatchEvent(new Event('auth:unauthorized'));
		}
		return Promise.reject(error);
	}
);