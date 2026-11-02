using Microsoft.EntityFrameworkCore;
using StationRetrofit.Api.Models;

namespace StationRetrofit.Api.Data;

public class AppDbContext : DbContext
{
    public AppDbContext(DbContextOptions<AppDbContext> options) : base(options) { }

    public DbSet<Product> Products => Set<Product>();
    public DbSet<PriceEntry> PriceEntries => Set<PriceEntry>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        base.OnModelCreating(modelBuilder);

        // Snake-case table names
        modelBuilder.Entity<Product>(entity =>
        {
            entity.ToTable("products");

            entity.Property(e => e.Id).HasColumnName("id");
            entity.Property(e => e.Name).HasColumnName("name").IsRequired().HasMaxLength(200);
            entity.Property(e => e.Sku).HasColumnName("sku").IsRequired().HasMaxLength(50);
            entity.Property(e => e.Status).HasColumnName("status");
            entity.Property(e => e.Category).HasColumnName("category");
            entity.Property(e => e.CreatedAt).HasColumnName("created_at");
            entity.Property(e => e.UpdatedAt).HasColumnName("updated_at");

            entity.HasMany(e => e.PriceEntries)
                .WithOne(p => p.Product)
                .HasForeignKey(p => p.ProductId)
                .OnDelete(DeleteBehavior.Cascade);
        });

        modelBuilder.Entity<PriceEntry>(entity =>
        {
            entity.ToTable("price_entries");

            entity.Property(e => e.Id).HasColumnName("id");
            entity.Property(e => e.ProductId).HasColumnName("product_id");
            entity.Property(e => e.Currency).HasColumnName("currency").IsRequired().HasMaxLength(3);
            entity.Property(e => e.Amount).HasColumnName("amount").HasColumnType("decimal(18,2)");
            entity.Property(e => e.Type).HasColumnName("price_type");
            entity.Property(e => e.Description).HasColumnName("description");
            entity.Property(e => e.ValidFrom).HasColumnName("valid_from");
            entity.Property(e => e.ValidTo).HasColumnName("valid_to");
            entity.Property(e => e.CreatedAt).HasColumnName("created_at");
        });
    }
}
