import { StationRetrofitApi } from './apis';

let client: StationRetrofitApi | null = null;

export function getApiClient(): StationRetrofitApi {
  if (!client) {
    client = new StationRetrofitApi('/api');
  }
  return client;
}
