// Favourites and history are shared by several views, so they are loaded here once.
import { api } from './api.js';
import { emit, on } from './util.js';

export const state = { favourites: [], history: [], recents: [] };

export async function loadPersonal() {
  try {
    const [f, h] = await Promise.all([api('/api/favourites'), api('/api/history')]);
    state.favourites = f.items;
    state.history = h.items;
    state.recents = h.recent_locations;
  } catch (e) {
    // keep old data; views show their own errors when they load
  }
  emit('personal:updated');
}

on('history:changed', loadPersonal);
on('favourites:changed', loadPersonal);

export const isFavourite = (name) =>
  !!name && state.favourites.some((f) => f.name.toLowerCase() === name.toLowerCase());
