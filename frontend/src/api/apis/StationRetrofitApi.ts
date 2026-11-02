import type { ProductDto } from '../models/ProductDto';
import type { CreateProductRequest } from '../models/CreateProductRequest';
import type { UpdateProductRequest } from '../models/UpdateProductRequest';
import type { PriceEntryDto } from '../models/PriceEntryDto';
import type { CreatePriceRequest } from '../models/CreatePriceRequest';

export class StationRetrofitApi {
  private baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  private async request<T>(path: string, options?: RequestInit): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    });
    if (!response.ok) {
      throw new Error(`API error: ${response.status} ${response.statusText}`);
    }
    if (response.status === 204) return undefined as T;
    return response.json();
  }

  async listProducts(): Promise<ProductDto[]> {
    return this.request<ProductDto[]>('/products');
  }

  async getProduct(id: number): Promise<ProductDto> {
    return this.request<ProductDto>(`/products/${id}`);
  }

  async createProduct(body: CreateProductRequest): Promise<ProductDto> {
    return this.request<ProductDto>('/products', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  }

  async updateProduct(id: number, body: UpdateProductRequest): Promise<ProductDto> {
    return this.request<ProductDto>(`/products/${id}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    });
  }

  async deleteProduct(id: number): Promise<void> {
    return this.request<void>(`/products/${id}`, { method: 'DELETE' });
  }

  async listPrices(productId?: number): Promise<PriceEntryDto[]> {
    const query = productId !== undefined ? `?productId=${productId}` : '';
    return this.request<PriceEntryDto[]>(`/prices${query}`);
  }

  async createPrice(body: CreatePriceRequest): Promise<PriceEntryDto> {
    return this.request<PriceEntryDto>('/prices', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  }

  async deletePrice(id: number): Promise<void> {
    return this.request<void>(`/prices/${id}`, { method: 'DELETE' });
  }
}
